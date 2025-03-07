from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, CallbackContext
from shopify import Shopify
from dotenv import load_dotenv
import qrcode
import os
import datetime
import math
import requests
from babel.numbers import format_currency
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Inicio del bot
load_dotenv()

# Shopify API setup
SHOP_DOMAIN = os.getenv('SHOP_DOMAIN', '')
API_KEY = os.getenv('API_KEY', '')
API_PASSWORD = os.getenv('API_PASSWORD', '')

# Inicializar la instancia de Shopify
shopify = Shopify(SHOP_DOMAIN, API_KEY, API_PASSWORD)

# Telegram setup
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
dispatcher = updater.dispatcher

# Google Sheets API setup
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
credentials = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(credentials)

# Specify the Google Sheets document and worksheet
spreadsheet_key = os.getenv('GSPREAD_API_KEY', '')
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

# Get the TRM from government data
def get_trm():
    url = "https://www.datos.gov.co/resource/mcec-87by.json"
    response = requests.get(url)
    data = response.json()
    trm = float(data[0]["valor"])
    return trm

# Convert to USD the amount of the order
def convert_to_usd(amount_cop):
    trm = get_trm()
    amount_usd = float(amount_cop) / trm
    return round(amount_usd, 2)

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

def handle_message(update: Update, context: CallbackContext):
    global order_number, state, transaction_hash, total_with_commission, crypto_choice, order_total, trm_value, order_total_usd
    if state == "AWAITING_ORDER_NUMBER":
        order_number = update.message.text
        order = shopify.get_order(order_number)

        if not order:
            context.bot.send_message(chat_id=update.effective_chat.id, text="La orden no ha sido encontrada. Por favor, ingresa nuevamente el número de orden.")
            return

        order_status = order.get('status')
        if order_status != 'pending':
            context.bot.send_message(chat_id=update.effective_chat.id, text=f"La orden ya fue actualizada, estado de la orden: {order_status}.")
            return

        order_total = float(order.get('total_price'))  # Total in COP
        order_items = order.get('line_items')
        meta_data = order.get('meta_data', [])
        order_total_formatted = format_currency(order_total, 'COP', locale='es_CO')

        bot_fields_exist = any(meta.get('key') == 'txn_hash' or meta.get('key') == 'network' for meta in meta_data)
        if bot_fields_exist:
            context.bot.send_message(chat_id=update.effective_chat.id, text="No es posible actualizar la transacción a través del bot. Por favor, contáctanos en https://kiris.store para resolver tu problema, puede corregir su número de orden a continuación")
            state = None
            start(update, context)  # Restart the bot by calling the start() function
            return

        items_text = ""
        for item in order_items:
            items_text += f"{item.get('quantity')}x {item.get('title')}\n"

        context.bot.send_message(chat_id=update.effective_chat.id, text=f"Detalles de la orden:\nEstado: {order_status}\nTotal: {order_total_formatted}\nArtículos:\n{items_text}")
        context.bot.send_message(chat_id=update.effective_chat.id, text=f"Un momento...")

        # Get the TRM value
        trm_value = get_trm()

        # Convert the total from COP to USD
        order_total_usd = convert_to_usd(order_total)

        # Calculate the total to be paid with a 5% commission
        commission_decimal = float(os.getenv('COMMISSION_VALUE', '')) / 100  # Convert the value to decimal
        total_with_commission = math.ceil(round(order_total_usd * (1 + commission_decimal), 2))

        message = f"Total a pagar: ${total_with_commission:.2f} USDT\n\nPor favor, ten en cuenta que sólo aceptamos USDT o USDC. NO ENVIAR UN TOKEN DIFERENTE.\n\nEl precio actual del dólar en COP es {trm_value}. Se ha agregado un porcentaje mínimo de comisión al monto total para cubrir los costos de monetización."

        # Send the message to the user
        context.bot.send_message(chat_id=update.effective_chat.id, text=message)

        keyboard = [[
                     InlineKeyboardButton("TRON (TRC20)", callback_data='TRON'),
                     InlineKeyboardButton("ETH (ERC20)", callback_data='ETH')]]

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

def button(update: Update, context: CallbackContext):
    global order_number, state, transaction_hash, total_with_commission, crypto_choice, order_total, trm_value, order_total_usd
    query = update.callback_query
    if state == "AWAITING_CRYPTO_CHOICE":
        crypto_choice = query.data

        wallet_addresses = {
            'ETH': os.getenv('WALLET_ADDRESS_ETH', ''),
            'TRON': os.getenv('WALLET_ADDRESS_TRON', '')
        }

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
        context.bot.send_message(chat_id=update.effective_chat.id, text=f"El total a pagar es: ${total_with_commission} USDT")
        context.bot.send_message(chat_id=update.effective_chat.id, text=f"Por favor realiza el pago y envíanos el hash de la transacción en forma de texto por este medio, se actualizará tu orden y verificaremos tu pago, en caso de tener alguna duda, comunícate con nosotros en https://kiris.store")

        state = "AWAITING_TRANSACTION_HASH"
    elif state == "AWAITING_HASH_CONFIRMATION":
        if query.data == 'yes':
            # Guardar la información en un archivo Excel
            order_data = {
                "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # Convertir a cadena de texto
                "API_URL": SHOP_DOMAIN,
                "order": order_number,
                "order_total": order_total,
                "TRM": trm_value,
                "order_total_usd": order_total_usd,
                "total_with_commission": total_with_commission,
                "txn_hash": transaction_hash,
                "network": crypto_choice
            }

            # Conectar con el documento de Google Sheets
            sheet = client.open_by_key(spreadsheet_key)
            worksheet = sheet.worksheet(worksheet_name)

            # Agregar los datos del pedido al documento de Google Sheets
            worksheet.append_row(list(order_data.values()))

            print(f"La información se ha guardado en el archivo: {sheet}")

            data = {
                "metafields": [
                    {
                        "key": "txn_hash",
                        "value": transaction_hash,
                        "value_type": "string",
                        "namespace": "global"
                    },
                    {
                        "key": "network",
                        "value": crypto_choice,
                        "value_type": "string",
                        "namespace": "global"
                    }
                ]
            }

            response = shopify.update_order(order_number, data)

            if 'order' in response:  # Verificar si el pedido se actualizó correctamente
                context.bot.send_message(chat_id=update.effective_chat.id, text="La orden se ha actualizado con éxito.")
            else:
                context.bot.send_message(chat_id=update.effective_chat.id, text="Hubo un problema al actualizar la orden.")

            context.bot.send_message(chat_id=update.effective_chat.id, text="Gracias por tu información. Tu orden ha sido actualizada, pronto recibirá un correo electrónico con el estado de su pedido. ¡Hasta luego!")
            state = None
        else:
            transaction_hash = None
            context.bot.send_message(chat_id=update.effective_chat.id, text="Por favor, proporciona nuevamente el hash de la transacción.")
            state = "AWAITING_TRANSACTION_HASH"

start_handler = CommandHandler('start', start)
dispatcher.add_handler(start_handler)

message_handler = MessageHandler(Filters.text & (~Filters.command), handle_message)
dispatcher.add_handler(message_handler)

button_handler = CallbackQueryHandler(button)
dispatcher.add_handler(button_handler)

updater.start_polling()
