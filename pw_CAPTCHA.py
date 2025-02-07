from playwright.sync_api import sync_playwright

## IMPORTANT ##
## fill the dictionary below with your details ##
proxies = {
  "server": "http://brd.superproxy.io:33335",
  "username": 'brd-customer-<customer_id>-zone-<zone-name>',
  "password": '<zone-password>'
}

# initiallize playwright
pw = sync_playwright().start()

# create Firefox browser object
browser = pw.firefox.launch(
    # uncomment the lines below if you're using a web driver
    #headless=False, 
    #slow_mo=2000,
    proxy=proxies
)

# create new browser tab
page = browser.new_page()
# navigate to web page locked by CAPTCHA
page.goto("http://www.walmart.com")

# locate search input
page.locator("xpath=//input[@aria-label='Search']").fill("testing")
# submit search term
page.keyboard.press('Enter');

browser.close()
