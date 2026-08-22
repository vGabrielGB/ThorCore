import requests
from bs4 import BeautifulSoup
from decimal import Decimal
import urllib3

# Suppress insecure request warnings for BCV (they often have SSL issues)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def scrape_bcv_rate():
    try:
        url = "https://www.bcv.org.ve/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, verify=False, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        dolar_div = soup.find('div', id='dolar')
        if not dolar_div:
            return None, "No se encontró el contenedor del dólar en el sitio del BCV."

        valor_str = dolar_div.find('strong').text.strip()
        # BCV formats numbers as '36,50120000'
        valor_str = valor_str.replace(',', '.')
        
        return Decimal(valor_str), None
    except requests.RequestException as e:
        return None, f"Error de conexión con el BCV: {str(e)}"
    except Exception as e:
        return None, f"Error al procesar la página del BCV: {str(e)}"

def scrape_binance_usdt():
    try:
        url = 'https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search'
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Content-Type': 'application/json'
        }
        
        # BUY (Lowest value)
        payload_buy = {'fiat':'VES','page':1,'rows':10,'tradeType':'BUY','asset':'USDT','countries':[],'proMerchantAds':False,'shieldMerchantAds':False,'publisherType':None,'payTypes':[],'classifies':['mass','fee','system']}
        res_buy = requests.post(url, json=payload_buy, headers=headers, timeout=10)
        res_buy.raise_for_status()
        buy_data = res_buy.json()
        if not buy_data.get('data'):
            return None, "No se encontraron anuncios de compra (BUY) en Binance."
        buy_price = Decimal(buy_data['data'][0]['adv']['price'])
        
        # SELL (Highest value)
        payload_sell = {'fiat':'VES','page':1,'rows':10,'tradeType':'SELL','asset':'USDT','countries':[],'proMerchantAds':False,'shieldMerchantAds':False,'publisherType':None,'payTypes':[],'classifies':['mass','fee','system']}
        res_sell = requests.post(url, json=payload_sell, headers=headers, timeout=10)
        res_sell.raise_for_status()
        sell_data = res_sell.json()
        if not sell_data.get('data'):
            return None, "No se encontraron anuncios de venta (SELL) en Binance."
        sell_price = Decimal(sell_data['data'][0]['adv']['price'])
        
        # Average
        promedio = (buy_price + sell_price) / Decimal('2.0')
        return round(promedio, 2), None
        
    except requests.RequestException as e:
        return None, f"Error de conexión con Binance P2P: {str(e)}"
    except Exception as e:
        return None, f"Error al procesar datos de Binance: {str(e)}"

if __name__ == "__main__":
    rate, err = scrape_bcv_rate()
    print(f"Rate: {rate}, Error: {err}")

from django.core.cache import cache

def get_cached_rates():
    rates = cache.get('tasas_cambio_dict')
    if rates is None:
        from .models import TasaCambio
        rates = {t.moneda: t for t in TasaCambio.objects.all()}
        cache.set('tasas_cambio_dict', rates, 3600)
    return rates

def get_cached_config():
    config = cache.get('configuracion_negocio')
    if config is None:
        from .models import ConfiguracionNegocio
        config = ConfiguracionNegocio.objects.first()
        cache.set('configuracion_negocio', config, 3600)
    return config
