from selenium import webdriver
from selenium.webdriver.chrome.options import Options

url = "https://ya.ru"
chrome_options = Options()
chrome_options.add_argument('--no-sandbox')
chrome_options.add_argument('--disable-dev-shm-usage')
# chrome_options.add_argument('--headless')  # Раскомментируйте, если не хотите видеть окно браузера

print("Попытка запуска браузера...")
driver = webdriver.Chrome(options=chrome_options)
print("Браузер успешно запущен!")

try:
    driver.get(url)
    print(f"Страница '{url}' успешно открыта!")
    print(f"Заголовок страницы: {driver.title}")
finally:
    driver.quit()
    print("Браузер закрыт.")