import os
from dotenv import load_dotenv
load_dotenv()

powerbi_frame = os.getenv("POWERBI_IFRAME_URL")

ip_dev = os.getenv("IP_DEV")
port_dev = os.getenv("PORT_DEV")
user_dev = os.getenv("USER_DEV")
pwd_dev = os.getenv("PWD_DEV")
db_dev = os.getenv("DB_DEV")

mongo_uri = os.getenv('MONGO_URI', "")
mongo_db = os.getenv('MONGO_DB', "")
mongo_collection_pedidos = os.getenv("MONGO_COLLECTION_PEDIDOS", "")