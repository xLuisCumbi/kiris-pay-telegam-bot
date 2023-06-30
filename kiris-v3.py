from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, CallbackContext
from woocommerce import API
from dotenv import load_dotenv
import qrcode
import os
import pandas as pd
import datetime
import math
import requests
from babel.numbers import format_currency
import gspread
from oauth2client.service_account import ServiceAccountCredentials


# Inicio del bot
load_dotenv()


API_URL=os.getenv('API_URL', '')
API_CONSUMER_KEY=os.getenv('API_CONSUMER_KEY', '')
API_CONSUMER_SECRET=os.getenv('API_CONSUMER_SECRET', '')
WALLET_ADDRESS_ETH=os.getenv('WALLET_ADDRESS_ETH', '')
WALLET_ADDRESS_TRON=os.getenv('WALLET_ADDRESS_TRON', '')
TELEGRAM_BOT_TOKEN=os.getenv('TELEGRAM_BOT_TOKEN', '')
COMMISSION_VALUE=os.getenv('COMMISSION_VALUE', '')
GSPREAD_API_KEY=os.getenv('GSPREAD_API_KEY', '')

# WooCommerce API setup
# Set up WooCommerce API
wcapi = API(
    url=API_URL,  # Your store URL
    consumer_key=API_CONSUMER_KEY,  # Your consumer key
    consumer_secret=API_CONSUMER_SECRET,  # Your consumer secret
    version="wc/v3"  # WooCommerce API version
)

# Define your wallet addresses here
wallet_addresses = {
    # 'BTC': 'bc1qcd22l6020zd94uw0jqldgr9gfeem2rumdln29g',
    'ETH': WALLET_ADDRESS_ETH,
    'TRON': WALLET_ADDRESS_TRON,
}

# Telegram setup
updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
dispatcher = updater.dispatcher

# Google Sheets API setup
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
credentials = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(credentials)

# Specify the Google Sheets document and worksheet
spreadsheet_key = GSPREAD_API_KEY
worksheet_name = "Transacciones"

# Global Variables
order_number = None
crypto_choice = None
transaction_hash = None
state = None
total_with_commission = None
order_total = None
trm_value = None
order_total_usd = None

# Get the TRM from goverment data
def get_trm():
    url = "https://www.datos.gov.co/resource/mcec-87by.json"
    response = requests.get(url)
    data = response.json()
    trm = data[0]["valor"]
    return trm

# Convert to USD the amount of the order
def convert_to_usd(amount_cop):
    trm = float(get_trm())
    amount_usd = float(amount_cop) / trm
    return round(amount_usd)

def start(update: Update, context: CallbackContext):
    global state
    state = "AWAITING_ORDER_NUMBER"

    # Check if the start command has any arguments
    if context.args and len(context.args) > 0:
        order_number = context.args[0]  # Extract the order number from the arguments
        # Process the order number as needed
        context.bot.send_message(chat_id=update.effective_chat.id, text=f"Numero de orden: {order_number}")
        print(f"Order number from request: {order_number}")  # Order number from request
    else:
        context.bot.send_message(chat_id=update.effective_chat.id, text="Hola, ¿cuál es tu número de orden?")

def handle_message(update: Update, context):
    global order_number, state, transaction_hash, total_with_commission, crypto_choice, order_total, trm_value, order_total_usd
    if state == "AWAITING_ORDER_NUMBER":
        order_number = update.message.text
        order_response = wcapi.get(f"orders/{order_number}")
        # print(f"order response: {order_response}")

        if order_response.status_code == 404:
            context.bot.send_message(chat_id=update.effective_chat.id, text="La orden no ha sido encontrada. Por favor, ingresa nuevamente el número de orden.")
            return

        order = order_response.json()
        # print(f"order: {order}")

        order_status          = order.get('status')
        if order_status != 'pending':
            context.bot.send_message(chat_id=update.effective_chat.id, text=f"La orden ya fue actualizada, estado de la orden: {order_status}.")
            return

        order_total           = order.get('total') # Total in COP
        order_items           = order.get('line_items')
        meta_data             = order.get('meta_data', [])
        order_total_formatted = format_currency(order_total, 'COP', locale='es_CO')

        # print(f"meta_data: {meta_data}")

        bot_fields_exist = any(meta.get('key') == 'txn_hash' or meta.get('key') == 'network' for meta in meta_data)
        if bot_fields_exist:
            context.bot.send_message(chat_id=update.effective_chat.id, text="No es posible actualizar la transacción a través del bot. Por favor, contáctanos en https://kiris.store para resolver tu problema, puede corregir su número de orden a continuación")
            state = None
            start(update, context)  # Restart the bot by calling the start() function
            return

        items_text = ""
        for item in order_items:
            items_text += f"{item.get('quantity')}x {item.get('name')}\n"

        context.bot.send_message(chat_id=update.effective_chat.id, text=f"Detalles de la orden:\nEstado: {order_status}\nTotal: {order_total_formatted}\nArtículos:\n{items_text}")
        context.bot.send_message(chat_id=update.effective_chat.id, text=f"Un momento...")

        # Obtener el valor de TRM
        trm_value = get_trm()

        # Convertir el total de COP a USD
        order_total_usd = convert_to_usd(order_total)

        # Calcular el total a pagar con un 5% de comisión
        # commission_decimal = float(COMMISSION_VALUE) / 100  # Convertir el valor a decimal
        # total_with_commission = math.ceil(round(order_total_usd * (1 + commission_decimal), 2))

        message = f"Total a pagar: ${order_total_usd:.2f} USDT\n\nPor favor, ten en cuenta que sólo aceptamos USDT en la red de TRON.\n\nEl precio actual del dólar en COP es {trm_value}."

        # Enviar el mensaje al usuario
        context.bot.send_message(chat_id=update.effective_chat.id, text=message)

        keyboard = [[InlineKeyboardButton("TRON (TRC20)", callback_data='TRON')]]

        reply_markup = InlineKeyboardMarkup(keyboard)

        update.message.reply_text('Por favor elige la red por la que desea hacer el pago:', reply_markup=reply_markup)
        state = "AWAITING_CRYPTO_CHOICE"
    elif state == "AWAITING_TRANSACTION_HASH":
        transaction_hash = update.message.text
        keyboard = [[InlineKeyboardButton("Sí", callback_data='yes'),
                     InlineKeyboardButton("No", callback_data='no')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(chat_id=update.effective_chat.id, text=f"Has proporcionado el hash: {transaction_hash}\n ¿Es correcto?", reply_markup=reply_markup)
        state = "AWAITING_HASH_CONFIRMATION"

def button(update: Update, context):
    global order_number, state, transaction_hash, total_with_commission, crypto_choice, order_total, trm_value, order_total_usd
    query = update.callback_query
    if state == "AWAITING_CRYPTO_CHOICE":
        crypto_choice = query.data
        wallet_address = wallet_addresses[crypto_choice]

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(wallet_address)
        qr.make(fit=True)

        img = qr.make_image(fill='black', back_color='white')
        qr_file = f"{crypto_choice}_wallet_qr.png"
        img.save(qr_file)

        context.bot.send_photo(chat_id=update.effective_chat.id, photo=open(qr_file, 'rb'))
        os.remove(qr_file)

        context.bot.send_message(chat_id=update.effective_chat.id, text=f"Has seleccionado: {crypto_choice}.")
        context.bot.send_message(chat_id=update.effective_chat.id, text=f"La dirección de la billetera es: ")
        context.bot.send_message(chat_id=update.effective_chat.id, text=f"{wallet_address}")
        context.bot.send_message(chat_id=update.effective_chat.id, text=f"El total a pagar es: ${order_total_usd} USDT")
        context.bot.send_message(chat_id=update.effective_chat.id, text=f"Por favor realiza el pago y envíanos el hash de la transacción en forma de texto por este medio, se actualizará tu orden y verificaremos tu pago, en caso de tener alguna duda, comunícate con nosotros en https://kiris.store")

        state = "AWAITING_TRANSACTION_HASH"
    elif state == "AWAITING_HASH_CONFIRMATION":
        if query.data == 'yes':
            # Guardar la información en un archivo Excel
            order_data = {
                "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # Convertir a cadena de texto
                "API_URL": API_URL,
                "order": order_number,
                "order_total": order_total,
                "TRM": trm_value,
                "order_total_usd": order_total_usd,
                "total_with_commission": total_with_commission,
                "txn_hash": transaction_hash,
                "network": crypto_choice,
                "wallet_address": wallet_address,
                "txn_status": ''
            }

            # Connect to the Google Sheets document
            sheet = client.open_by_key(spreadsheet_key)
            worksheet = sheet.worksheet(worksheet_name)

            # Append the order data to the worksheet
            worksheet.append_row(list(order_data.values()))

            print(f"La información se ha guardado en el archivo: {sheet}")

            data = {
                "status": "on-hold",
                "meta_data": [
                    {
                        "key": "txn_hash",
                        "value": transaction_hash
                    },
                    {
                        "key": "network",
                        "value": crypto_choice
                    }
                ]
            }

            response = wcapi.put(f"orders/{order_number}", data).json()

            # print(f"response: {response}")  # Order number from request

            if 'id' in response:  # Check if the order was updated successfully
                context.bot.send_message(chat_id=update.effective_chat.id, text="La orden se ha actualizado con éxito.")
            else:
                context.bot.send_message(chat_id=update.effective_chat.id, text="Hubo un problema al actualizar la orden.")

            context.bot.send_message(chat_id=update.effective_chat.id, text="Gracias por tu información. Tu orden ha sido actualizada, pronto recibirá un email con el estado de su pedido \n ¡Hasta luego!")
            state = None
        else:
            transaction_hash = None
            context.bot.send_message(chat_id=update.effective_chat.id, text="Por favor, proporciona nuevamente el hash de la transacción.")
            state = "AWAITING_TRANSACTION_HASH"

start_handler = CommandHandler('pagar', start)
dispatcher.add_handler(start_handler)

message_handler = MessageHandler(Filters.text & (~Filters.command), handle_message)
dispatcher.add_handler(message_handler)

button_handler = CallbackQueryHandler(button)
dispatcher.add_handler(button_handler)

updater.start_polling()
