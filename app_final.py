from flask import Flask, request, session, send_file
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import time
import io
import os
import urllib.request
import json
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

app = Flask(__name__)
app.secret_key = 'supersecretkey_2026_fittap'

# --- Шрифт для кириллицы в PDF ---
font_path = os.path.join(os.path.dirname(__file__), 'Roboto-Regular.ttf')
if not os.path.exists(font_path):
    try:
        urllib.request.urlretrieve(
            'https://github.com/googlefonts/Roboto/raw/main/src/hinted/Roboto-Regular.ttf',
            font_path
        )
    except Exception as e:
        print(f"Не удалось скачать шрифт: {e}")
        print("Скачайте Roboto-Regular.ttf вручную и положите в папку с проектом.")
        exit(1)
pdfmetrics.registerFont(TTFont('Roboto', font_path))
# --------------------------------

def check_accessibility(url):
    chrome_options = Options()
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    # chrome_options.add_argument('--headless')

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    driver.get(url)
    time.sleep(3)

    # 1. Размер кликабельных элементов
    clickables = driver.find_elements(By.CSS_SELECTOR, 'a, button, [role="button"], input[type="submit"]')
    size_issues = []
    for el in clickables:
        is_visible = driver.execute_script("""
            var el = arguments[0];
            var style = window.getComputedStyle(el);
            return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0' && el.offsetWidth > 0 && el.offsetHeight > 0;
        """, el)
        if not is_visible:
            continue
        size = el.size
        width = size['width']
        height = size['height']
        if width < 44 or height < 44:
            is_warning = (width >= 24 and height >= 24)
            size_issues.append({
                'tag': el.tag_name,
                'text': el.text[:40] if el.text and el.text.strip() else '(без текста)',
                'width': width,
                'height': height,
                'warning': is_warning
            })

    # 2. Контрастность текста
    contrast_script = """
    function isVisible(el) {
        let style = window.getComputedStyle(el);
        return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
    }
    function getBgColor(el) {
        let bg = window.getComputedStyle(el).backgroundColor;
        if (bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent') {
            return el.parentElement ? getBgColor(el.parentElement) : 'rgb(255,255,255)';
        }
        return bg;
    }
    function luminance(r,g,b) {
        let rs = r/255, gs = g/255, bs = b/255;
        rs = rs <= 0.03928 ? rs/12.92 : Math.pow((rs+0.055)/1.055, 2.4);
        gs = gs <= 0.03928 ? gs/12.92 : Math.pow((gs+0.055)/1.055, 2.4);
        bs = bs <= 0.03928 ? bs/12.92 : Math.pow((bs+0.055)/1.055, 2.4);
        return 0.2126*rs + 0.7152*gs + 0.0722*bs;
    }
    function contrastRatio(rgb1, rgb2) {
        let l1 = luminance(rgb1.r, rgb1.g, rgb1.b);
        let l2 = luminance(rgb2.r, rgb2.g, rgb2.b);
        let lighter = Math.max(l1, l2);
        let darker = Math.min(l1, l2);
        return (lighter + 0.05) / (darker + 0.05);
    }
    function parseRgb(rgbStr) {
        let m = rgbStr.match(/\\d+/g);
        if (m && m.length >= 3) return {r: parseInt(m[0]), g: parseInt(m[1]), b: parseInt(m[2])};
        return null;
    }
    let issues = [];
    let elements = document.querySelectorAll('body *');
    for (let el of elements) {
        if (!isVisible(el)) continue;
        let text = el.innerText?.trim();
        if (!text || text.length < 5) continue;
        let tag = el.tagName.toLowerCase();
        if (tag === 'script' || tag === 'style' || tag === 'meta' || tag === 'link') continue;
        let bgColor = getBgColor(el);
        let textColor = window.getComputedStyle(el).color;
        let fontSize = parseFloat(window.getComputedStyle(el).fontSize);
        let isLarge = (fontSize >= 18) || (fontSize >= 14 && window.getComputedStyle(el).fontWeight === 'bold');
        let requiredRatio = isLarge ? 3.0 : 4.5;
        let rgbText = parseRgb(textColor);
        let rgbBg = parseRgb(bgColor);
        if (rgbText && rgbBg) {
            let ratio = contrastRatio(rgbText, rgbBg);
            if (ratio < requiredRatio) {
                issues.push({
                    tag: el.tagName,
                    text: text.substring(0, 60).replace(/\\n/g, ' '),
                    contrast: ratio.toFixed(2),
                    required: requiredRatio
                });
            }
        }
    }
    return issues;
    """
    contrast_issues = driver.execute_script(contrast_script)

    # 3. ARIA-навигация (Walkthrough Score)
    aria_script = """
    let focusableElements = [];
    let elements = document.querySelectorAll('a, button, input, select, textarea, [tabindex]:not([tabindex="-1"])');
    elements.forEach(el => {
        let isFocusable = true;
        let style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') isFocusable = false;
        focusableElements.push({
            tag: el.tagName,
            text: (el.innerText || el.value || '').trim().substring(0, 40),
            focusable: isFocusable
        });
    });
    let total = focusableElements.length;
    let focusableCount = focusableElements.filter(el => el.focusable).length;
    return { total, focusableCount, elements: focusableElements };
    """
    aria_data = driver.execute_script(aria_script)
    walkthrough_score = round((aria_data['focusableCount'] / max(aria_data['total'], 1)) * 100, 1)

    driver.quit()

    return {
        'url': url,
        'total_clickables': len(clickables),
        'size_issues': size_issues[:50],
        'size_issues_count': len(size_issues),
        'contrast_issues': contrast_issues[:50],
        'contrast_issues_count': len(contrast_issues),
        'aria': {
            'total': aria_data['total'],
            'focusable': aria_data['focusableCount'],
            'score': walkthrough_score,
            'elements': aria_data['elements'][:20]
        }
    }

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        url = request.form.get('url')
        if not url:
            return render_home_page(error='Введите URL!')
        try:
            result = check_accessibility(url)
            session['last_result'] = result
            return render_result_page(result)
        except Exception as e:
            return render_home_page(error=f'Ошибка: {str(e)}')
    return render_home_page()

@app.route('/download/pdf')
def download_pdf():
    result = session.get('last_result')
    if not result:
        return "Нет результатов. Сначала проведите аудит.", 400

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=20*mm, leftMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('TitleStyle', parent=styles['Title'], fontName='Roboto', fontSize=18, textColor=colors.HexColor('#1e3c72'))
    heading_style = ParagraphStyle('Heading', parent=styles['Heading2'], fontName='Roboto', fontSize=14, textColor=colors.HexColor('#2a5298'))
    normal_style = ParagraphStyle('Normal', parent=styles['Normal'], fontName='Roboto', fontSize=10)

    story = []
    story.append(Paragraph("FitTap — отчёт об аудите доступности", title_style))
    story.append(Spacer(1, 10*mm))
    story.append(Paragraph(f"<b>URL:</b> {result['url']}", normal_style))
    story.append(Spacer(1, 5*mm))
    story.append(Paragraph(f"<b>Кликабельные элементы:</b> всего {result['total_clickables']}, из них проблемных (размер &lt;44px): {result['size_issues_count']}", normal_style))
    story.append(Paragraph(f"<b>Контрастность текста:</b> нарушений {result['contrast_issues_count']}", normal_style))
    story.append(Paragraph(f"<b>Walkthrough Score (ARIA):</b> {result['aria']['score']}%", normal_style))
    story.append(Spacer(1, 10*mm))

    if result['size_issues']:
        story.append(Paragraph("Проблемы с размером кликабельных элементов:", heading_style))
        data = [[Paragraph("Тег", normal_style), Paragraph("Текст", normal_style), Paragraph("Размер (px)", normal_style), Paragraph("Примечание", normal_style)]]
        for issue in result['size_issues'][:20]:
            note = "Предупреждение" if issue.get('warning', False) else "Критично"
            data.append([Paragraph(issue['tag'], normal_style), Paragraph(issue['text'], normal_style), Paragraph(f"{issue['width']}×{issue['height']}", normal_style), Paragraph(note, normal_style)])
        t = Table(data, colWidths=[30*mm, 80*mm, 35*mm, 35*mm])
        t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('BACKGROUND', (0,0), (-1,0), colors.lightgrey)]))
        story.append(t)
        story.append(Spacer(1, 10*mm))

    if result['contrast_issues']:
        story.append(Paragraph("Проблемы с контрастностью текста:", heading_style))
        data2 = [[Paragraph("Тег", normal_style), Paragraph("Текст (начало)", normal_style), Paragraph("Контраст", normal_style), Paragraph("Требуется", normal_style)]]
        for issue in result['contrast_issues'][:20]:
            data2.append([Paragraph(issue['tag'], normal_style), Paragraph(issue['text'], normal_style), Paragraph(issue['contrast'], normal_style), Paragraph(str(issue['required']), normal_style)])
        t2 = Table(data2, colWidths=[30*mm, 70*mm, 30*mm, 30*mm])
        t2.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('BACKGROUND', (0,0), (-1,0), colors.lightgrey)]))
        story.append(t2)

    doc.build(story)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f'fittap_report_{int(time.time())}.pdf', mimetype='application/pdf')

def render_home_page(error=None):
    error_html = f'<div class="error">{error}</div>' if error else ''
    return f'''
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>FitTap — проверка доступности сайтов</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,300;400;600;700;800&display=swap" rel="stylesheet">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
        <style>
            * {{ margin:0; padding:0; box-sizing:border-box; }}
            body {{
                font-family: 'Inter', sans-serif;
                background: radial-gradient(circle at 20% 30%, #1a1f2e, #0f121c);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 2rem;
                position: relative;
                overflow-x: hidden;
            }}
            body::before {{
                content: '';
                position: absolute;
                width: 200%;
                height: 200%;
                top: -50%;
                left: -50%;
                background: conic-gradient(from 0deg, #ff6b6b, #4ecdc4, #45b7d1, #96f0b6, #ff6b6b);
                animation: rotate 20s linear infinite;
                z-index: 0;
                opacity: 0.15;
            }}
            @keyframes rotate {{ 100% {{ transform: rotate(360deg); }} }}
            .glass-card {{
                position: relative;
                z-index: 2;
                background: rgba(20, 24, 35, 0.7);
                backdrop-filter: blur(16px);
                border-radius: 2.5rem;
                padding: 3rem 2.5rem;
                max-width: 1100px;
                width: 100%;
                box-shadow: 0 25px 45px rgba(0,0,0,0.3), 0 0 0 1px rgba(255,255,255,0.1);
                transition: transform 0.3s ease;
            }}
            .glass-card:hover {{ transform: translateY(-5px); }}
            .logo-container {{
                display: flex;
                justify-content: center;
                align-items: center;
                gap: 1rem;
                margin-bottom: 1rem;
                flex-wrap: wrap;
            }}
            .logo-svg {{
                width: 60px;
                height: 60px;
                filter: drop-shadow(0 0 8px rgba(78,205,196,0.3));
            }}
            h1 {{
                font-size: 3rem;
                font-weight: 800;
                background: linear-gradient(135deg, #ffffff, #4ecdc4);
                -webkit-background-clip: text;
                background-clip: text;
                color: transparent;
                letter-spacing: -0.02em;
            }}
            .tagline {{ color: #b9c3d9; margin-bottom: 2rem; text-align: center; font-weight: 300; }}
            .input-group {{ display: flex; gap: 1rem; margin: 2rem 0; flex-wrap: wrap; }}
            .url-input {{ flex: 1; background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.2); padding: 1rem 1.5rem; border-radius: 3rem; color: white; font-size: 1rem; transition: all 0.2s; }}
            .url-input:focus {{ outline: none; border-color: #4ecdc4; background: rgba(255,255,255,0.15); box-shadow: 0 0 0 3px rgba(78,205,196,0.2); }}
            .check-btn {{ background: linear-gradient(135deg, #4ecdc4, #45b7d1); border: none; padding: 0 2rem; border-radius: 3rem; font-weight: 600; font-size: 1rem; cursor: pointer; transition: transform 0.2s, box-shadow 0.2s; }}
            .check-btn:hover {{ transform: scale(1.02); box-shadow: 0 8px 20px rgba(78,205,196,0.3); }}
            .features {{ display: flex; justify-content: center; gap: 2rem; margin: 1rem 0 1.5rem; flex-wrap: wrap; }}
            .feature-item {{ color: #b9c3d9; font-size: 0.9rem; display: flex; align-items: center; gap: 0.5rem; }}
            .feature-item i {{ color: #4ecdc4; font-size: 1.1rem; }}
            .info-block {{
                background: rgba(255,255,255,0.05);
                border-radius: 1.5rem;
                padding: 1.3rem 1.5rem;
                margin: 1.2rem 0;
                border: 1px solid rgba(255,255,255,0.1);
            }}
            .info-block h3 {{
                color: #4ecdc4;
                font-size: 1.2rem;
                margin-bottom: 0.75rem;
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }}
            .info-block p {{
                color: #cbd5e0;
                font-size: 0.9rem;
                line-height: 1.4;
                margin-bottom: 0.3rem;
            }}
            .criteria-grid {{
                display: flex;
                gap: 1rem;
                flex-wrap: wrap;
                margin-top: 0.5rem;
            }}
            .criterion-card {{
                flex: 1;
                background: rgba(0,0,0,0.4);
                border-radius: 1rem;
                padding: 1rem;
                border-left: 4px solid #f56565;
            }}
            .criterion-title {{
                font-weight: 700;
                color: #fbd38d;
                font-size: 1rem;
                margin-bottom: 0.5rem;
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }}
            .criterion-desc {{
                color: #e2e8f0;
                font-size: 0.85rem;
                margin-bottom: 0.5rem;
            }}
            .law-badge {{
                display: inline-block;
                background: #dc2626;
                color: white;
                font-size: 0.65rem;
                padding: 0.2rem 0.5rem;
                border-radius: 1rem;
                margin-top: 0.3rem;
            }}
            .persona-grid {{
                display: flex;
                gap: 1rem;
                flex-wrap: wrap;
                margin-top: 0.5rem;
            }}
            .persona-card {{
                flex: 1;
                background: rgba(0,0,0,0.3);
                border-radius: 1rem;
                padding: 0.8rem;
                text-align: center;
            }}
            .persona-icon {{
                font-size: 2rem;
                margin-bottom: 0.3rem;
            }}
            .persona-title {{
                font-weight: 700;
                color: #fbd38d;
            }}
            .persona-desc {{
                font-size: 0.75rem;
                color: #cbd5e0;
                margin-top: 0.3rem;
            }}
            .footer {{
                margin-top: 1.5rem;
                font-size: 0.75rem;
                color: #5f6c84;
                text-align: center;
                border-top: 1px solid rgba(255,255,255,0.1);
                padding-top: 1.5rem;
                display: flex;
                flex-direction: column;
                gap: 0.25rem;
            }}
            .error {{ background: #dc2626; color: white; padding: 0.5rem; border-radius: 2rem; margin-top: 1rem; text-align: center; }}
            @media (max-width: 700px) {{
                .glass-card {{ padding: 2rem 1.5rem; }}
                h1 {{ font-size: 2rem; }}
                .persona-grid, .criteria-grid {{ flex-direction: column; }}
            }}
        </style>
    </head>
    <body>
        <div class="glass-card">
            <div class="logo-container">
                <svg class="logo-svg" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <defs>
                        <linearGradient id="logoGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                            <stop offset="0%" stop-color="#1e3c72"/>
                            <stop offset="100%" stop-color="#4ecdc4"/>
                        </linearGradient>
                        <linearGradient id="fingerGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                            <stop offset="0%" stop-color="#ffffff"/>
                            <stop offset="100%" stop-color="#d0f0f0"/>
                        </linearGradient>
                    </defs>
                    <rect x="28" y="28" width="44" height="44" rx="8" stroke="url(#logoGrad)" stroke-width="2.5" fill="none"/>
                    <line x1="50" y1="28" x2="50" y2="72" stroke="#4ecdc4" stroke-width="1.5" opacity="0.6"/>
                    <line x1="28" y1="50" x2="72" y2="50" stroke="#4ecdc4" stroke-width="1.5" opacity="0.6"/>
                    <path d="M50 34 C 42 34, 36 40, 36 48 L 36 52 C 36 58, 40 62, 45 62 C 48 62, 50 59, 50 56 C 50 53, 48 50, 46 50 C 44 50, 42 52, 42 54" stroke="url(#fingerGrad)" stroke-width="3" fill="none" stroke-linecap="round"/>
                    <path d="M50 34 C 58 34, 64 40, 64 48 L 64 52 C 64 58, 60 62, 55 62 C 52 62, 50 59, 50 56" stroke="url(#fingerGrad)" stroke-width="3" fill="none" stroke-linecap="round"/>
                    <circle cx="50" cy="48" r="3" fill="#4ecdc4" opacity="0.7"/>
                </svg>
                <h1>FitTap</h1>
            </div>
            <div class="tagline">автоматическая проверка доступности веб-сайтов по стандартам WCAG 2.1</div>

            <form method="POST">
                <div class="input-group">
                    <input type="url" name="url" class="url-input" placeholder="https://yandex.ru" required>
                    <button type="submit" class="check-btn"><i class="fas fa-search"></i> Аудит</button>
                </div>
            </form>
            {error_html}

            <!-- Блок критериев WCAG -->
            <div class="info-block">
                <h3><i class="fas fa-gavel"></i> Ключевые критерии WCAG 2.1 — правовая основа</h3>
                <div class="criteria-grid">
                    <div class="criterion-card">
                        <div class="criterion-title"><i class="fas fa-hand-pointer"></i> 2.5.5 — Размер цели</div>
                        <div class="criterion-desc">Интерактивные элементы <strong>не менее 44×44 пикселей</strong>.</div>
                        <span class="law-badge">Обязательно</span>
                    </div>
                    <div class="criterion-card">
                        <div class="criterion-title"><i class="fas fa-adjust"></i> 1.4.3 — Контрастность</div>
                        <div class="criterion-desc">Контраст текста: <strong>обычный ≥4.5:1, крупный ≥3:1</strong>.</div>
                        <span class="law-badge">Законодательно</span>
                    </div>
                </div>
            </div>

            <!-- Блок "Для кого этот сервис" -->
            <div class="info-block">
                <h3><i class="fas fa-users"></i> Для кого этот сервис</h3>
                <div class="persona-grid">
                    <div class="persona-card">
                        <div class="persona-icon">🖐️</div>
                        <div class="persona-title">Люди с нарушениями моторики</div>
                        <div class="persona-desc">Тремор, слабый контроль движений — нужны крупные кнопки (≥44px).</div>
                    </div>
                    <div class="persona-card">
                        <div class="persona-icon">👁️</div>
                        <div class="persona-title">Люди с нарушениями зрения</div>
                        <div class="persona-desc">Слабовидящие, дальтонизм — важен высокий контраст текста (≥4.5:1).</div>
                    </div>
                    <div class="persona-card">
                        <div class="persona-icon">⌨️</div>
                        <div class="persona-title">Пользователи скринридеров</div>
                        <div class="persona-desc">Не видят экран — нужна правильная ARIA-разметка и фокус клавиатуры.</div>
                    </div>
                </div>
            </div>

            <div class="features">
                <div class="feature-item"><i class="fas fa-arrows-alt"></i> Размер ≥44×44px</div>
                <div class="feature-item"><i class="fas fa-adjust"></i> Контрастность текста</div>
                <div class="feature-item"><i class="fas fa-file-pdf"></i> PDF-отчёт</div>
                <div class="feature-item"><i class="fas fa-keyboard"></i> ARIA-навигация</div>
            </div>

            <div class="footer">
                <div>© 2026 FitTap | Проект участницы конференции (Казань)</div>
                <div><i class="fas fa-github"></i> <a href="#">Исходный код и описание проекта</a></div>
            </div>
        </div>
    </body>
    </html>
    '''

def render_result_page(result):
    size_issues_js = result['size_issues']
    contrast_issues_js = result['contrast_issues']
    size_issues_json = json.dumps(size_issues_js)
    contrast_issues_json = json.dumps(contrast_issues_js)

    size_issues_html = ''
    for idx, issue in enumerate(size_issues_js):
        warning_class = 'warning' if issue.get('warning', False) else 'critical'
        warning_text = '⚠️ Предупреждение' if issue.get('warning', False) else '❌ Критично'
        size_issues_html += f'''
        <div class="issue-card {warning_class}" data-type="size" data-idx="{idx}">
            <div class="issue-tag"><i class="fas fa-code"></i> {issue['tag']}</div>
            <div class="issue-text">"{issue['text']}"</div>
            <div class="issue-size"><i class="fas fa-ruler"></i> {issue['width']}×{issue['height']} px</div>
            <div class="issue-note">{warning_text}</div>
            <button class="fix-btn">💡 Исправить</button>
        </div>
        '''
    if not size_issues_html:
        size_issues_html = '<div class="no-issues"><i class="fas fa-check-circle"></i> ✅ Все видимые элементы крупнее 44×44 px</div>'

    contrast_issues_html = ''
    for idx, issue in enumerate(contrast_issues_js):
        contrast_issues_html += f'''
        <div class="issue-card critical" data-type="contrast" data-idx="{idx}">
            <div class="issue-tag"><i class="fas fa-palette"></i> {issue['tag']}</div>
            <div class="issue-text">"{issue['text']}"</div>
            <div class="issue-size">Контраст {issue['contrast']}:1 (норма ≥{issue['required']}:1)</div>
            <button class="fix-btn">💡 Исправить</button>
        </div>
        '''
    if not contrast_issues_html:
        contrast_issues_html = '<div class="no-issues"><i class="fas fa-check-circle"></i> ✅ Контрастность в порядке</div>'

    aria_items_html = ''
    for el in result['aria']['elements'][:20]:
        focus_status = '✅' if el['focusable'] else '❌'
        aria_items_html += f'<div class="aria-item">{focus_status} <strong>{el["tag"]}</strong> — {el["text"]}</div>'

    return f'''
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>FitTap — результат аудита</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:opsz@14..32&display=swap" rel="stylesheet">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
        <style>
            * {{ margin:0; padding:0; box-sizing:border-box; }}
            body {{ background: radial-gradient(circle at 20% 30%, #1a1f2e, #0f121c); font-family: 'Inter', sans-serif; padding: 2rem; min-height: 100vh; }}
            .container {{ max-width: 1300px; margin: 0 auto; }}
            .result-glass {{ background: rgba(20,24,35,0.75); backdrop-filter: blur(12px); border-radius: 2rem; padding: 2rem; box-shadow: 0 20px 35px rgba(0,0,0,0.3); }}
            .back-link {{ display: inline-flex; align-items: center; gap: 0.5rem; color: #4ecdc4; text-decoration: none; margin-bottom: 1rem; transition: 0.2s; }}
            .back-link:hover {{ color: #96f0b6; }}
            .info-note {{ background: rgba(78,205,196,0.15); border-left: 4px solid #4ecdc4; padding: 0.8rem; margin: 1rem 0; border-radius: 1rem; font-size: 0.85rem; color: #cbd5e0; }}
            .persona-selector {{ background: rgba(0,0,0,0.3); padding: 0.5rem 1rem; border-radius: 2rem; display: inline-block; margin-bottom: 1rem; }}
            .persona-selector select {{ background: rgba(255,255,255,0.2); border: none; color: white; padding: 0.3rem 0.8rem; border-radius: 2rem; cursor: pointer; }}
            h2 {{ font-size: 1.5rem; color: white; word-break: break-all; margin-top: 0.5rem; margin-bottom: 1rem; }}
            h3 {{ color: #f0f4f8; margin-top: 2rem; margin-bottom: 0.5rem; font-weight: 600; }}
            .stats {{ display: flex; gap: 1rem; margin: 1rem 0; flex-wrap: wrap; }}
            .stat-box {{ background: rgba(255,255,255,0.08); border-radius: 2rem; padding: 0.5rem 1rem; color: #e2e8f0; }}
            .stat-box.bad {{ background: rgba(220,38,38,0.2); color: #ffb3b3; }}
            .stat-box.good {{ background: rgba(72,187,120,0.2); color: #c6f6d5; }}
            .issues-grid {{ display: flex; flex-direction: column; gap: 0.8rem; margin-bottom: 1.5rem; }}
            .issue-card {{ background: rgba(0,0,0,0.3); border-radius: 1rem; padding: 0.8rem; display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; }}
            .issue-card.critical {{ border-left: 4px solid #dc2626; }}
            .issue-card.warning {{ border-left: 4px solid #fbbf24; }}
            .issue-tag {{ font-family: monospace; background: #2d3748; border-radius: 1rem; padding: 0.2rem 0.6rem; color: #fbd38d; font-size: 0.8rem; }}
            .issue-text {{ color: #e2e8f0; font-size: 0.85rem; flex: 2; }}
            .issue-size {{ color: #fc8181; font-weight: 500; }}
            .issue-note {{ font-size: 0.7rem; padding: 0.2rem 0.5rem; border-radius: 1rem; }}
            .issue-card.critical .issue-note {{ background: rgba(245,101,101,0.2); color: #ffb3b3; }}
            .issue-card.warning .issue-note {{ background: rgba(251,191,36,0.2); color: #fde68a; }}
            .fix-btn {{ background: #4ecdc4; border: none; padding: 0.2rem 0.8rem; border-radius: 2rem; font-size: 0.7rem; cursor: pointer; transition: 0.2s; margin-left: auto; }}
            .fix-btn:hover {{ background: #45b7d1; transform: scale(1.02); }}
            .no-issues {{ background: rgba(72,187,120,0.2); border-radius: 1rem; padding: 1rem; text-align: center; color: #c6f6d5; }}
            .aria-section {{ margin-top: 2rem; }}
            .aria-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 0.5rem; margin: 1rem 0; }}
            .aria-item {{ background: rgba(0,0,0,0.25); padding: 0.4rem 0.8rem; border-radius: 0.5rem; font-size: 0.8rem; color: #e2e8f0; }}
            .pdf-btn {{ background: linear-gradient(135deg, #f56565, #ed64a6); border: none; padding: 0.6rem 1.2rem; border-radius: 2rem; color: white; cursor: pointer; margin-top: 2rem; display: inline-block; text-decoration: none; font-weight: 500; transition: 0.2s; }}
            .pdf-btn:hover {{ transform: translateY(-2px); filter: brightness(1.05); }}
            .modal {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.8); justify-content: center; align-items: center; z-index: 1000; backdrop-filter: blur(4px); }}
            .modal-content {{ background: #1e293b; border-radius: 1.5rem; padding: 1.5rem; max-width: 550px; width: 90%; color: #f1f5f9; box-shadow: 0 20px 35px rgba(0,0,0,0.5); }}
            .modal-content pre {{ background: #0f172a; padding: 0.8rem; border-radius: 0.8rem; overflow-x: auto; font-size: 0.8rem; color: #facc15; }}
            .close-modal {{ float: right; cursor: pointer; font-size: 1.5rem; color: #94a3b8; }}
            .close-modal:hover {{ color: white; }}
            @media (max-width: 700px) {{ .issue-card {{ flex-direction: column; align-items: flex-start; }} .issue-text {{ max-width: 100%; }} .fix-btn {{ margin-left: 0; margin-top: 0.5rem; }} }}
        </style>
        <script>
            const sizeIssues = {size_issues_json};
            const contrastIssues = {contrast_issues_json};
            function showFix(type, idx) {{
                let issue, fixText = '';
                if (type === 'size') {{
                    issue = sizeIssues[idx];
                    fixText = `<strong>Проблема:</strong> элемент <code>${{issue['tag']}}</code> имеет размер ${{issue['width']}}×${{issue['height']}} px, что меньше рекомендованных 44×44 px.<br><br>
                    <strong>Рекомендация:</strong> увеличьте кликабельную область.<br><br>
                    <strong>Пример CSS:</strong><pre>.element-class {{\n  min-width: 44px;\n  min-height: 44px;\n  padding: 10px;\n  display: inline-block;\n}}</pre><br>
                    <strong>Пояснение:</strong> люди с нарушениями моторики (тремор, слабый контроль движений) испытывают трудности при нажатии на мелкие элементы. Увеличение области нажатия до 44×44 пикселей делает интерфейс доступнее.`;
                }} else if (type === 'contrast') {{
                    issue = contrastIssues[idx];
                    fixText = `<strong>Проблема:</strong> элемент <code>${{issue['tag']}}</code> имеет контраст ${{issue['contrast']}}:1, что ниже нормы WCAG (${{issue['required']}}:1).<br><br>
                    <strong>Рекомендация:</strong> измените цвета фона или текста для повышения контраста.<br><br>
                    <strong>Пример CSS:</strong><pre>.element-class {{\n  color: #000000;\n  background-color: #ffffff;\n}}</pre><br>
                    <strong>Пояснение:</strong> слабовидящие люди не могут прочитать текст с низким контрастом. Обеспечьте контраст не менее 4.5:1 для обычного текста.`;
                }}
                document.getElementById('modal-text').innerHTML = fixText;
                document.getElementById('fix-modal').style.display = 'flex';
            }}
            function closeModal() {{ document.getElementById('fix-modal').style.display = 'none'; }}
            function changePersona(value) {{
                let message = '';
                if (value === 'default') message = '👤 Обычный пользователь: критерии WCAG (44px, контраст 4.5:1).';
                else if (value === 'elderly') message = '👵 Пожилой человек: рекомендуются более крупные кнопки (48+px) и усиленный контраст (7:1). На этом сайте многие элементы будут неудобны.';
                else if (value === 'colorblind') message = '🎨 Дальтоник (протанопия): красные/зелёные оттенки могут сливаться. Проверьте, не потерян ли смысл интерфейса.';
                alert(message);
            }}
            document.addEventListener('DOMContentLoaded', function() {{
                document.querySelectorAll('.fix-btn').forEach(btn => {{
                    btn.addEventListener('click', function(e) {{
                        const card = this.closest('.issue-card');
                        const type = card.getAttribute('data-type');
                        const idx = parseInt(card.getAttribute('data-idx'), 10);
                        showFix(type, idx);
                    }});
                }});
            }});
        </script>
    </head>
    <body>
        <div class="container">
            <div class="result-glass">
                <a href="/" class="back-link"><i class="fas fa-arrow-left"></i> Новый аудит</a>
                <div class="info-note">
                    <i class="fas fa-info-circle"></i> FitTap анализирует сайт по строгим критериям WCAG (размер цели ≥44×44px, контраст ≥4.5:1). 
                    Элементы размером от 24 до 44 пикселей — «Предупреждение», менее 24px — «Критично».
                </div>
                <div class="persona-selector">
                    <label style="color:white;">👥 Тестирование для: </label>
                    <select id="persona" onchange="changePersona(this.value)">
                        <option value="default">Обычный пользователь</option>
                        <option value="elderly">👵 Пожилой человек (плохое зрение/моторика)</option>
                        <option value="colorblind">🎨 Дальтоник (протанопия)</option>
                    </select>
                </div>
                <h2><i class="fas fa-chart-simple"></i> Отчёт для <span style="color:#4ecdc4;">{result['url']}</span></h2>
                <div class="stats">
                    <div class="stat-box">🔘 Видимых кликабельных: {result['total_clickables']}</div>
                    <div class="stat-box {'bad' if result['size_issues_count']>0 else 'good'}">
                        ⚠️ Проблемных по размеру: {result['size_issues_count']}
                    </div>
                    <div class="stat-box {'bad' if result['contrast_issues_count']>0 else 'good'}">
                        🎨 Контраст: {result['contrast_issues_count']} нарушений
                    </div>
                    <div class="stat-box {'bad' if result['aria']['score'] < 70 else 'good'}">
                        ⌨️ Walkthrough Score: {result['aria']['score']}%
                    </div>
                </div>
                <h3>❗ Проблемы с размером</h3>
                <div class="issues-grid">{size_issues_html}</div>
                <h3>🎨 Проблемы с контрастностью</h3>
                <div class="issues-grid">{contrast_issues_html}</div>
                <div class="aria-section">
                    <h3>⌨️ ARIA-навигация (Walkthrough Score)</h3>
                    <div class="stats">
                        <div class="stat-box">Всего интерактивных: {result['aria']['total']}</div>
                        <div class="stat-box">Доступно для Tab: {result['aria']['focusable']}</div>
                    </div>
                    <div class="aria-grid">{aria_items_html}</div>
                </div>
                <a href="/download/pdf" class="pdf-btn"><i class="fas fa-file-pdf"></i> Скачать PDF-отчёт</a>
                <div style="margin-top: 1.5rem; font-size: 0.7rem; color: #7f8fa4;">WCAG 2.1: размер цели ≥44×44px, контраст ≥4.5:1 (3:1 для крупного текста)</div>
            </div>
        </div>
        <div id="fix-modal" class="modal" onclick="if(event.target===this) closeModal()">
            <div class="modal-content">
                <span class="close-modal" onclick="closeModal()">&times;</span>
                <h3>💡 Рекомендация по исправлению</h3>
                <div id="modal-text" style="margin-top: 1rem;"></div>
            </div>
        </div>
    </body>
    </html>
    '''

if __name__ == '__main__':
    app.run(debug=True)