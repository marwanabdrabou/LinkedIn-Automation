import streamlit as st
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.action_chains import ActionChains
import logging
import time
import pandas as pd
from datetime import datetime, time as dt_time
import os
from urllib.parse import urlparse
import threading
import schedule
import openpyxl
from bs4 import BeautifulSoup
from selenium.webdriver.chrome.options import Options


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()

# Constants
MAX_MESSAGES_PER_DAY = 10
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sent_messages.xlsx")
COLUMNS = ["Email", "ProfileURL", "Name", "Title", "Date", "Message"]
LOGIN_TIMEOUT = 120  # Increased timeout for CAPTCHA handling

# Initialize session state for scheduler
if 'scheduler_running' not in st.session_state:
    st.session_state.scheduler_running = False
if 'scheduled_time' not in st.session_state:
    st.session_state.scheduled_time = None

# Streamlit interface
st.title("LinkedIn Automation Messages")

# Sidebar for settings
with st.sidebar:
    st.header("Settings")
    max_messages = st.number_input("Max messages per day", min_value=1, max_value=20, value=10)
    delay_between_messages = st.number_input("Delay between messages (seconds)", min_value=1, max_value=60, value=10)
    manual_captcha = st.checkbox("Enable manual CAPTCHA solving", value=True)
    st.info(f"Messages will be limited to {max_messages} per day")

    # Scheduling section
    st.header("Scheduling")
    enable_scheduler = st.checkbox("Enable Daily Scheduling")
    
    if enable_scheduler:
        col1, col2 = st.columns(2)
        with col1:
            schedule_hour = st.number_input("Hour (24h format)", min_value=0, max_value=23, value=9)
        with col2:
            schedule_minute = st.number_input("Minute", min_value=0, max_value=59, value=0)
        
        if st.button("Set Schedule"):
            st.session_state.scheduled_time = f"{schedule_hour:02d}:{schedule_minute:02d}"
            st.success(f"Messages scheduled daily at {st.session_state.scheduled_time}")
            st.session_state.scheduler_running = True
        
        if st.button("Stop Scheduling"):
            schedule.clear()
            st.session_state.scheduler_running = False
            st.warning("Daily scheduling stopped")
    
    if st.session_state.scheduler_running:
        st.info(f"Scheduler active - will run daily at {st.session_state.scheduled_time}")

# Main input fields
col1, col2 = st.columns(2)
with col1:
    LINKEDIN_EMAIL = st.text_input("LinkedIn Email:")
with col2:
    LINKEDIN_PASSWORD = st.text_input("LinkedIn Password:", type="password")

title = st.text_input("Search for people with this title:")
message = st.text_area("Message to send:")

def load_sent_messages():
    try:
        if os.path.exists(DATA_FILE):
            df = pd.read_excel(DATA_FILE)
            # Ensure all required columns exist
            for col in COLUMNS:
                if col not in df.columns:
                    if col == "Date":
                        df[col] = pd.NaT
                    else:
                        df[col] = None
            # Convert Date column to datetime
            if 'Date' in df.columns:
                df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
            return df
        return pd.DataFrame(columns=COLUMNS)
    except Exception as e:
        logger.error(f"Error loading sent messages: {str(e)}")
        return pd.DataFrame(columns=COLUMNS)

def save_sent_messages(df):
    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        
        # Ensure all required columns exist before saving
        for col in COLUMNS:
            if col not in df.columns:
                if col == "Date":
                    df[col] = pd.NaT
                else:
                    df[col] = None
        
        # Convert Date column to datetime if it exists
        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        
        # Save to Excel with openpyxl engine
        df.to_excel(DATA_FILE, index=False, engine='openpyxl')
        return True
    except Exception as e:
        logger.error(f"Error saving sent messages: {str(e)}")
        return False


def check_daily_limit():
    try:
        df = load_sent_messages()
        if df.empty or 'Date' not in df.columns:
            return False
            
        today = datetime.now().date()
        # Filter valid dates
        valid_dates = df[df['Date'].notna()]
        if valid_dates.empty:
            return False
            
        today_messages = valid_dates[valid_dates['Date'].dt.date == today]
        return len(today_messages) >= max_messages
    except Exception as e:
        logger.error(f"Error checking daily limit: {str(e)}")
        return False

def get_profile_id(url):
    try:
        if pd.isna(url) or not isinstance(url, str):
            return None
        parsed = urlparse(url)
        path = parsed.path.strip('/')
        if path.startswith('in/'):
            return path.split('/')[1]
        return None
    except Exception as e:
        logger.error(f"Error extracting profile ID: {str(e)}")
        return None

def linkedin_login(driver):
    try:
        driver.get('https://www.linkedin.com/login')
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "username")))

        username = driver.find_element(By.ID, "username")
        password = driver.find_element(By.ID, "password")

        # Type credentials slowly to appear more human-like
        actions = ActionChains(driver)
        actions.send_keys_to_element(username, LINKEDIN_EMAIL).perform()
        time.sleep(1)
        actions.send_keys_to_element(password, LINKEDIN_PASSWORD).perform()
        time.sleep(1)
        
        # Click login button
        driver.find_element(By.XPATH, "//button[@type='submit']").click()
        
        # Handle CAPTCHA if enabled
        if manual_captcha:
            st.warning("Please complete the CAPTCHA verification if prompted")
            WebDriverWait(driver, LOGIN_TIMEOUT).until(
                lambda d: "feed" in d.current_url.lower() or "checkpoint/challenge" in d.current_url.lower())
            
            if "checkpoint/challenge" in driver.current_url.lower():
                st.warning("CAPTCHA verification required. Please solve it manually in the browser window.")
                WebDriverWait(driver, LOGIN_TIMEOUT).until(
                    lambda d: "feed" in d.current_url.lower())
        
        # Verify successful login
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.XPATH, "//input[@aria-label='Search']")))
        
        logger.info("Successfully logged in")
        return True
    
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        # Check for specific error messages
        try:
            error = driver.find_element(By.ID, "error-for-password").text
            st.error(f"Login failed: {error}")
        except:
            st.error("Login failed. Please check your credentials and try again.")
        return False

def get_profile_info(driver):
    try:
        # Get current URL (profile URL)
        current_url = driver.current_url
        
        # Get profile name
        name_element = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//h1[contains(@class, 'text-heading-xlarge')]")))
        profile_name = name_element.text.strip()
        
        return current_url, profile_name
    except Exception as e:
        logger.error(f"Error getting profile info: {str(e)}")
        return None, "Unknown"

def is_duplicate_recipient(df, profile_url):
    if df.empty or 'ProfileURL' not in df.columns:
        return False
    
    profile_id = get_profile_id(profile_url)
    if not profile_id:
        return False
    
    existing_ids = df['ProfileURL'].apply(get_profile_id)
    return profile_id in existing_ids.values

def extract_profiles_from_html(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    profiles = []
    
    # Find all profile containers
    profile_containers = soup.find_all('li', class_='tDfphBmQslIXKQzHkydHYPMOKfvxiBLINLOBw')
    
    for container in profile_containers:
        try:
            # Extract profile URL
            profile_link = container.find('a', {
                'class': 'onRHPXypfWLuNOCinrLJfqDJJJaXLBUXSKz',
                'data-test-app-aware-link': True
            })
            
            if not profile_link or not profile_link.get('href'):
                continue
                
            profile_url = profile_link['href'].split('?')[0]  # Clean URL
            
            # Extract profile name
            name_span = profile_link.find('span', {'aria-hidden': 'true'})
            profile_name = name_span.get_text(strip=True) if name_span else "Unknown"
            
            # Extract headline
            headline_div = container.find('div', class_='TmhqKVgxpVFoDdYnKiMIkkTPeoywzixNLXovdrw')
            headline = headline_div.get_text(strip=True) if headline_div else ""
            
            # Extract location
            location_div = container.find('div', class_='eDoCapdtCHaaqGmFnsIyAPMKjrgPGOOrQ')
            location = location_div.get_text(strip=True) if location_div else ""
            
            profiles.append({
                'name': profile_name,
                'url': profile_url,
                'headline': headline,
                'location': location
            })
            
        except Exception as e:
            logger.warning(f"Error extracting profile: {str(e)}")
            continue
    
    return profiles

def search_and_send_messages(title, message):
    if check_daily_limit():
        st.warning(f"You've already sent the maximum {MAX_MESSAGES_PER_DAY} messages today.")
        return
    
    sent_messages = load_sent_messages()
    driver = None
    
    try:
        
        chrome_options = Options()
    
        # Headless mode (no GUI)
        chrome_options.add_argument("--headless=new")  # New headless mode in Chrome 109+
        chrome_options.add_argument("--no-sandbox")  # Bypass OS security
        chrome_options.add_argument("--disable-dev-shm-usage")  # Prevent crashes in Docker/Linux
        # Initialize Chrome driver
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()),
                                  options=chrome_options)
        
        # Login
        st.write("Logging in to LinkedIn...")
        if not linkedin_login(driver):
            st.error("Login failed. Please check your credentials.")
            return
        
        # Search for people
        st.write(f"Searching for people with title: {title}")
        search_button = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.XPATH, "//button[@aria-label='Click to start a search']")))
        search_button.click()

        search_bar = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.XPATH, "//input[@aria-label='Search']")))
        search_bar.send_keys(title)
        search_bar.send_keys(Keys.RETURN)

        # Wait for search results and filter to people
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CLASS_NAME, "search-results-container")))
        
        # Filter people
        WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'People')]"))).click()
        WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(., '1st')]"))).click()
        time.sleep(2)
        
        # Wait for search results to load
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".search-results-container")))
        
        # Scroll to load more results
        last_height = driver.execute_script("return document.body.scrollHeight")
        while True:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

        # Extract profile information using BeautifulSoup
        page_source = driver.page_source
        profiles = extract_profiles_from_html(page_source)
        
        if not profiles:
            st.warning("No profiles found in search results")
            return
            
        st.write(f"Found {len(profiles)} profiles")
        
        # Find all message buttons
        message_buttons = WebDriverWait(driver, 20).until(
            EC.presence_of_all_elements_located((By.XPATH, "//button[.//span[text()='Message']]")))
        
        # Limit to remaining messages for today
        today = datetime.now().date()
        if not sent_messages.empty and 'Date' in sent_messages.columns:
            today_messages = sent_messages[sent_messages['Date'].dt.date == today]
            remaining_messages = max(0, max_messages - len(today_messages))
        else:
            remaining_messages = max_messages
            
        message_buttons = message_buttons[:remaining_messages]
        
        if not message_buttons:
            st.warning("No message buttons found or daily limit reached")
            return
            
        progress_bar = st.progress(0)
        status_text = st.empty()
        stats = {'sent': 0, 'duplicates': 0, 'errors': 0}
        
        # Send messages
        for i, message_button in enumerate(message_buttons):
            try:
                if i >= len(profiles):
                    break  # Safety check
                
                profile = profiles[i]
                profile_url = profile['url']
                profile_name = profile['name']
                
                # Update progress
                progress = (i + 1) / len(message_buttons)
                progress_bar.progress(progress)
                
                # Click message button
                driver.execute_script("arguments[0].click();", message_button)
                time.sleep(3)
                
                # Check for duplicates
                if is_duplicate_recipient(sent_messages, profile_url):
                    stats['duplicates'] += 1
                    status_text.text(f"Skipping duplicate recipient {i+1} of {len(message_buttons)}")
                    
                    # Close chat
                    close_button = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, 
                            "//button[contains(@class, 'msg-overlay-bubble-header__control')]//*[contains(@data-test-icon, 'close-small')]/ancestor::button")))
                    driver.execute_script("arguments[0].click();", close_button)
                    time.sleep(1)
                    continue
                
                status_text.text(f"Sending message {i+1} of {len(message_buttons)} to {profile_name}")
                
                # Type message
                main_div = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//div[starts-with(@class, 'msg-form__msg-content-container')]")))
                main_div.click()
                paragraphs = driver.find_elements(By.TAG_NAME, "p")
                paragraphs[-5].send_keys(message)
                
                # Send message
                send_button = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.XPATH, 
                        "//button[@type='submit' and contains(@class, 'msg-form__send-button')]")))
                driver.execute_script("arguments[0].click();", send_button)
                
                st.success(f"Message sent to {profile_name}")
                logger.info(f"Message sent to {profile_name} - {profile_url}")

                stats['sent'] += 1
                
                # Record sent message
                new_entry = pd.DataFrame({
                    "Email": [LINKEDIN_EMAIL],
                    "ProfileURL": [profile_url],
                    "Name": [profile_name],
                    "Title": [title],
                    "Date": [datetime.now()],
                    "Message": [message]
                })
                # Ensure all columns exist in the new entry
                for col in COLUMNS:
                    if col not in new_entry.columns:
                        new_entry[col] = None
                
                # Handle empty DataFrames properly
                if sent_messages.empty:
                    sent_messages = new_entry
                else:
                    sent_messages = pd.concat([sent_messages, new_entry], ignore_index=True)
                
                save_sent_messages(sent_messages)

                # sent_messages = pd.concat([sent_messages, new_entry], ignore_index=True)
                # save_sent_messages(sent_messages)
                
                # Close chat
                close_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, 
                        "//button[contains(@class, 'msg-overlay-bubble-header__control')]//*[contains(@data-test-icon, 'close-small')]/ancestor::button")))
                driver.execute_script("arguments[0].click();", close_button)
                
                time.sleep(delay_between_messages)
                
            except Exception as e:
                stats['errors'] += 1
                st.error(f"Failed to send message to recipient {i+1}: {str(e)}")
                logger.error(f"Error sending message: {str(e)}")
                continue
                
        progress_bar.empty()
        status_text.text(f"Completed! Sent {stats['sent']} messages, skipped {stats['duplicates']} duplicates, {stats['errors']} errors.")
        
    except Exception as e:
        st.error(f"An error occurred: {str(e)}")
        logger.error(f"Script error: {str(e)}")
    finally:
        if driver:
            driver.quit()

# Scheduler thread function
def run_scheduler():
    while st.session_state.scheduler_running:
        schedule.run_pending()
        time.sleep(1)

# Start scheduler thread if not already running
if st.session_state.scheduler_running and not hasattr(st.session_state, 'scheduler_thread'):
    st.session_state.scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    st.session_state.scheduler_thread.start()

# Button to trigger the search and send messages function
if st.button("Send Messages Now"):
    if not LINKEDIN_EMAIL or not LINKEDIN_PASSWORD:
        st.error("Please provide both email and password.")
    elif not title or not message:
        st.error("Please provide both title and message.")
    else:
        with st.spinner("Processing..."):
            search_and_send_messages(title, message)

# Show sent messages history
if st.checkbox("Show sent messages history"):
    df = load_sent_messages()
    if not df.empty:
        st.dataframe(df)
        today_count = len(df[df['Date'].dt.date == datetime.now().date()]) if 'Date' in df.columns else 0
        st.info(f"Messages sent today: {today_count}/{max_messages}")
        
        # Show duplicate prevention info
        unique_recipients = df['ProfileURL'].nunique() if 'ProfileURL' in df.columns else 0
        st.info(f"Unique recipients contacted: {unique_recipients}")
    else:
        st.info("No messages sent yet")

# Add button to clear history (for testing)
if st.checkbox("Show admin options"):
    if st.button("Clear Sent Messages History"):
        if os.path.exists(DATA_FILE):
            os.remove(DATA_FILE)
            st.success("Message history cleared")
        else:
            st.warning("No message history file found")