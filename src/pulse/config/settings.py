import os
from dotenv import load_dotenv
load_dotenv()

powerbi_frame = os.getenv("POWERBI_IFRAME_URL")

ip_dev = os.getenv("IP_DEV")
port_dev = os.getenv("PORT_DEV")
user_dev = os.getenv("USER_DEV")
pwd_dev = os.getenv("PWD_DEV")
db_dev = os.getenv("DB_DEV")