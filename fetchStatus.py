import os
import time
import glob
import pickle
import requests
import undetected_chromedriver as uc

from dotenv import load_dotenv
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

WORK_HEADLESS=False
WAIT_TIMEOUT_SECONDS=25
MID_WAIT_TIMEOUT_SECONDS=5
MICRO_WAIT_TIMEOUT_SECONDS=1

BASE_URL='https://wisetekmarket-restuff.eu/'
SUB_URL='collections/macbooks?sort_by=price-ascending&filter.v.availability=1'
LOGIN_SCREEN_SPECIFIC_TEXT='This content is protected. Please log in with your customer account to continue.'
TELEGRAM_FILE_NAME='dumps.pkl'
load_dotenv()


class AuthManager:
	def __init__(self, chrome_driver):
		self.driver = chrome_driver
		self.username = os.getenv("RESTUFF_USERNAME")
		self.password = os.getenv("RESTUFF_PASSWORD")
		self.__loadValidCookies()

	def isLoggedIn(self):
		try:
			print("Trying to find if we are logged in.")
			element_present = EC.presence_of_element_located((By.TAG_NAME, 'p'))
			WebDriverWait(self.driver, WAIT_TIMEOUT_SECONDS).until(element_present)
			p_elements = self.driver.find_elements(By.TAG_NAME, 'p')
			for p in p_elements:
				if LOGIN_SCREEN_SPECIFIC_TEXT in p.text:
					return False
			print("Logged In Successfully")
			return True
		except TimeoutException:
			return False
		return False


	def __loadValidCookies(self):
		self.driver.get(BASE_URL+SUB_URL)
		if not self.isLoggedIn():
			self.__loginAndSaveCookies()
			
	def __loginAndSaveCookies(self):
		print("No Login found, Trying to login..")
		email_field = WebDriverWait(self.driver, WAIT_TIMEOUT_SECONDS).until(EC.presence_of_element_located((By.ID, "customer-email")))
		password_field = self.driver.find_element(By.ID, "customer-password")
		login_button = self.driver.find_element(By.XPATH, "//button[@class='btn btn--primary w-full']")

		email_field.send_keys(self.username)
		password_field.send_keys(self.password)

		time.sleep(MICRO_WAIT_TIMEOUT_SECONDS)
		login_button.click()

		try:
			WebDriverWait(self.driver, WAIT_TIMEOUT_SECONDS).until(lambda driver: (self.driver.current_url == BASE_URL+SUB_URL))
			time.sleep(MID_WAIT_TIMEOUT_SECONDS)
			print("Logged In Successfully")
		except TimeoutException:
			print("Unable to Login with the Provided Keys or the internet may be too slow. Tip: check the .env file to verify keys.")


class TelegramNotifier():
	def __init__(self):
		self.mode = ''
		self.addlist = False

		self.bot_token = os.getenv("RESTUFF_TELEGRAM_BOT_TOKEN")
		self.chat_id = os.getenv("RESTUFF_CHAT_ID")

		self.data = self.__loadOldData()
		self.filter_price = self.data.get('filter_price', 30000)
		self.banned_products = self.data.get('banned_products', [])
		print("Current Data: ", self.data)

		self.__getMessages()

	def isListRequested(self):
		return self.addlist

	def getBannedProductList(self):
		return self.banned_products

	def getFilterPrice(self):
		return self.filter_price

	def sendMessage(self, message, parse_mode = 'Markdown'):
		url = f'https://api.telegram.org/bot{self.bot_token}/sendMessage'
		response = requests.post(url, data={'chat_id': self.chat_id, 'text': message, 'parse_mode': parse_mode})

	def __getMessages(self):
		last_message_offset = self.data.get('update_id', 0)
		print("Last Message Offset: ", last_message_offset)
		all_messages = requests.get(f'https://api.telegram.org/bot{self.bot_token}/getUpdates?offset={last_message_offset}').json()
		for message in all_messages['result']:
			if message['message']['from']['id'] != int(self.chat_id):
				continue

			if message['message']['text'] == '/listproduct':
				self.addlist = True
			elif message['message']['text'] == '/addproduct':
				self.mode = 'add'
			elif message['message']['text'] == '/removeproduct':
				self.mode = 'remove'
			elif message['message']['text'] == '/triggerprice':
				self.mode = 'trigger'			
			elif message['message']['text'].isdigit():
				if self.mode == 'add':
					self.banned_products.append(int(message['message']['text']))
				elif self.mode == 'remove':
					self.banned_products.remove(int(message['message']['text']))
				elif self.mode == 'trigger':
					self.filter_price = int(message['message']['text'])
			self.data['update_id'] = message['update_id']+1
		
		self.data['banned_products'] = self.banned_products
		self.data['filter_price'] = self.filter_price
		print("Currently banned Products: ",self.banned_products)
		self.__exportOldData()

	def __loadOldData(self):
		if os.path.exists(TELEGRAM_FILE_NAME):
			file = open(TELEGRAM_FILE_NAME, 'rb')
			return pickle.load(file)
		else:
			return dict()

	def __exportOldData(self):
		with open(TELEGRAM_FILE_NAME, 'wb') as file:
			pickle.dump(self.data, file)


class Automator:
	def __init__(self, headless=False):
		self.driver = uc.Chrome(headless=WORK_HEADLESS)
		self.telegram_notifier = TelegramNotifier()
		self.auth_manager = AuthManager(self.driver)
		self.product_list = []
		self.trigger_price = self.telegram_notifier.getFilterPrice()
		self.banned_products = self.telegram_notifier.getBannedProductList()

	def unleash(self):
		self.__checkProductsAndNotify()

	def __checkProductsAndNotify(self):
		if not self.auth_manager.isLoggedIn():
			print("No Working Cookies Found, Quitting ...")
			return

		time.sleep(MID_WAIT_TIMEOUT_SECONDS)
		print("Fetching Product List")
		self.__getProductList()


	def __getProductList(self):
		products = self.driver.execute_script("return meta;")['products']
		for product in products:
			for variant in product['variants']:
				if variant['id'] not in self.banned_products:
					self.product_list.append(variant)

		self.product_list = sorted(self.product_list, key=lambda x: x['price'])

		print("Number of Products Found: ", len(self.product_list))

		if self.telegram_notifier.isListRequested():
			message = ""
			data = []
			for product in self.product_list:
				message += f'**ID**:\t`{product['id']}`\n**Price**:\t{product['price']/100}\n**Name**:\t{product['name']}\n\n'

			if len(self.banned_products)>0:
				message+="Banned Products:\n"
				for product in self.banned_products:
					message+=f'ID: `{product}`'

			self.telegram_notifier.sendMessage(message)


		alert_message = ''
		for product in self.product_list:
			if product['price']/100 < self.trigger_price:
				alert_message += f'**ID**:\t`{product['id']}`\n**Price**:\t{product['price']/100}\n**Name**:\t{product['name']}\n\n'

		if alert_message != '':
			print("Found Deals, Sending Alerts!")
			alert_message = '**Found Amazing Deals**\n\n' + alert_message + f'Check Link: [Link]({BASE_URL+SUB_URL})'
			self.telegram_notifier.sendMessage(alert_message)
		self.driver.quit()


if __name__ == '__main__':
	automator = Automator()
	automator.unleash()
