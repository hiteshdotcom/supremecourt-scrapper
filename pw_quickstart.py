from playwright.sync_api import sync_playwright

# initiallize playwright
pw = sync_playwright().start()
# create Firefox browser object
browser = pw.firefox.launch(
    # uncomment the lines below if you're using a web driver
    #headless=False, 
    #slow_mo=2000
)

# create new browser tab
page = browser.new_page()
# navigate to web page
page.goto("https://www.sci.gov.in/judgements-judgement-date/")

# web page details and source code
print(page.content())
print(page.title())
page.screenshot()

browser.close()
