import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
import os
from woocommerce import API
from dotenv import load_dotenv

# Inicio del bot
load_dotenv()

# Configuración de la API de Tron Scan
TRONSCAN_API_URL = 'https://apilist.tronscan.org/api/'
TRONSCAN_API_KEY = '41a1fbc9-d4a2-4ed2-9631-1ca59f116044'

# Configuración de la API de ETH
ETH_API_URL = 'https://api.etherscan.io/api/'
ETH_API_KEY = 'R98YJP93QSWF2R2H38HDT2WSKKWDXJXH56'

# Configuración de Google Sheets
GSPREAD_API_KEY='1k4n7XgcWMuZc14qMRDeJnxFHDwCcmArk6LnL6k25fqY'
WORKSHEET_NAME = 'Transacciones'

# Configuración de Woocommerce
WC_API_URL=os.getenv('WC_API_URL', '')
WC_CONSUMER_KEY=os.getenv('WC_CONSUMER_KEY', '')
WC_CONSUMER_SECRET=os.getenv('WC_CONSUMER_SECRET', '')

# Configurar la API de WooCommerce
wcapi = API(
    url=WC_API_URL,
    consumer_key=WC_CONSUMER_KEY,
    consumer_secret=WC_CONSUMER_SECRET,
    version="wc/v3"
)

# Conexión a Google Sheets
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
credentials = ServiceAccountCredentials.from_json_keyfile_name('../credentials.json', scope)
client = gspread.authorize(credentials)

# Obtener la hoja de cálculo y la hoja de trabajo
spreadsheet = client.open_by_key(GSPREAD_API_KEY)
worksheet = spreadsheet.worksheet(WORKSHEET_NAME)

# Obtener los registros del archivo de Excel
records = worksheet.get_all_records()

# Filtrar las transacciones no aprobadas
unapproved_records = [record for record in records if record['txn_status'] != 'Approved']

# Iterar sobre las transacciones no aprobadas y actualizar su estado
for record in unapproved_records:
    txn_hash = record['txn_hash']
    network = record['network']

    txn_status = None

    if network == 'TRON':
        # Consultar el estado de la transacción en Tron Scan
        url = f'{TRONSCAN_API_URL}transaction-info?hash={txn_hash}&apiKey={TRONSCAN_API_KEY}'
        response = requests.get(url)
        data = response.json()

        if 'confirmed' in data and data['confirmed']:
            txn_status = 'Approved'
        else:
            continue  # Saltar la actualización si la transacción no está confirmada

    elif network == 'ETH':
        # Consultar el estado de la transacción en la API de ETH
        url = f'{ETH_API_URL}?module=transaction&action=gettxreceiptstatus&txhash={txn_hash}&apikey={ETH_API_KEY}'
        response = requests.get(url)
        data = response.json()

        if 'status' in data and data['status'] == '1':
            txn_status = 'Approved'
        else:
            continue  # Saltar la actualización si la transacción no está aprobada

    # Actualizar el estado de la transacción en el archivo de Excel
    row_index = records.index(record) + 2  # Sumar 2 para tener en cuenta la fila de encabezado y el índice base 1
    worksheet.update_cell(row_index, 10, txn_status)  # 8 es el número de columna de 'txn_status'

    #if txn_status == 'Approved':
    #    order_number = record['order_number']
    #    order_data = {
    #        'status': 'processing'  # Actualizar el estado de la orden a 'completed'
    #    }
    #    wcapi.put(f'orders/{order_number}', order_data)  # Actualizar la orden en WooCommerce

print('Actualización de transacciones completada.')
