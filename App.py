import streamlit as st
import requests
import folium
import polyline
import pandas as pd
from datetime import datetime, timedelta
import streamlit.components.v1 as components

# --- 1. KONFIGURASJON ---
st.set_page_config(page_title="SikkerTur Pro v21.8", page_icon="🚗", layout="wide")

# --- 2. INITIALISERING ---
if "tabell_data" not in st.session_state:
    st.session_state.tabell_data = None
if "kart_html" not in st.session_state:
    st.session_state.kart_html = None

try:
    API_KEY = st.secrets["google_maps_api_key"]
except:
    st.error("API-nøkkel mangler i Streamlit Secrets!")
    st.stop()

# --- 3. HJELPEFUNKSJONER ---

def hent_lysforhold(lat, lon, dato):
    url = f"https://api.sunrise-sunset.org/json?lat={lat}&lng={lon}&date={dato.strftime('%Y-%m-%d')}&formatted=0"
    try:
        res = requests.get(url, timeout=5).json()
        if res['status'] == 'OK':
            opp = datetime.fromisoformat(res['results']['sunrise']) + timedelta(hours=1)
            ned = datetime.fromisoformat(res['results']['sunset']) + timedelta(hours=1)
            return opp.time(), ned.time()
    except: pass
    return None, None

def oversett_vaertype(symbol_kode):
    koder = {
        'clearsky': 'Klart vær', 'fair': 'Lettskyet', 'partlycloudy': 'Delvis skyet',
        'cloudy': 'Overskyet', 'rain': 'Regn', 'heavyrain': 'Kraftig regn',
        'lightrain': 'Lett regn', 'rainshowers': 'Regnbyger', 'snow': 'Snø',
        'heavysnow': 'Kraftig snø', 'lightsnow': 'Lett snø', 'snowshowers': 'Snøbyger',
        'sleet': 'Sludd', 'heavysleet': 'Kraftig sludd', 'lightsleet': 'Lett sludd',
        'fog': 'Tåke', 'thunder': 'Tordenvær'
    }
    ren_kode = symbol_kode.split('_')[0]
    return koder.get(ren_kode, ren_kode.capitalize())

def hent_vaer_detaljer(lat, lon, tid):
    headers = {'User-Agent': 'SikkerTurApp/v21.8'}
    url = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={round(lat, 4)}&lon={round(lon, 4)}"
    try:
        r = requests.get(url, headers=headers, timeout=5)
        data = r.json()
        target_time = tid.replace(tzinfo=None)
        timeseries = data['properties']['timeseries']
        best_match = min(timeseries, key=lambda x: abs((datetime.fromisoformat(x['time'].replace('Z', '')) - target_time).total_seconds()))
        instant = best_match['data']['instant']['details']
        neste_time = best_match['data'].get('next_1_hours', {})
        nedbor = neste_time.get('details', {}).get('precipitation_amount', 0)
        symbol = neste_time.get('summary', {}).get('symbol_code', 'clearsky_day')
        return {
            "temp": instant.get('air_temperature', 0),
            "vind": instant.get('wind_speed', 0),
            "kast": instant.get('wind_speed_of_gust', 0),
            "nedbor": nedbor,
            "vaertype": oversett_vaertype(symbol)
        }
    except: return {"temp": 0, "vind": 0, "kast": 0, "nedbor": 0, "vaertype": "Ukjent"}

def hent_kommune(lat, lon):
    url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lon}&key={API_KEY}&language=no"
    try:
        res = requests.get(url, timeout=5).json()
        for result in res['results']:
            for component in result['address_components']:
                if "administrative_area_level_2" in component['types']: return component['long_name']
    except: pass
    return "Ukjent"

def hent_hoyde(lat, lon):
    url = f"https://maps.googleapis.com/maps/api/elevation/json?locations={lat},{lon}&key={API_KEY}"
    try:
        res = requests.get(url, timeout=5).json()
        return int(res['results'][0]['elevation']) if res['status'] == 'OK' else 0
    except: return 0

def fargelegg_rader(row):
    styles = [''] * len(row)
    # Værtype er indeks 3, Lys er indeks 4
    if 'Snø' in str(row['Værtype']) or 'Sludd' in str(row['Værtype']):
        styles[3] = 'background-color: #003366; color: white; font-weight: bold'
    if row['Lys'] == '🌙 Mørkt':
        styles[4] = 'background-color: #2c3e50; color: #ecf0f1'
    return styles

# --- 4. SIDEBAR ---
st.sidebar.header("📍 Reiseplanlegger Pro")
fra = st.sidebar.text_input("Fra:", value="Oslo")
til = st.sidebar.text_input("Til:", value="Trondheim")
dato_inn = st.sidebar.date_input("Dato:", value=datetime.now())
tid_inn = st.sidebar.time_input("Tid:", value=datetime.now())
start_knapp = st.sidebar.button("🚀 Kjør Totalanalyse", type="primary")

# --- 5. LOGIKK ---
if start_knapp:
    with st.spinner('Henter stedsnavn, nedbør og lysforhold...'):
        avreise_dt = datetime.combine(dato_inn, tid_inn)
        route_url = f"https://maps.googleapis.com/maps/api/directions/json?origin={fra}&destination={til}&departure_time={int(avreise_dt.timestamp())}&key={API_KEY}&language=no"
        route_res = requests.get(route_url).json()

        if route_res['status'] == 'OK':
            leg = route_res['routes'][0]['legs'][0]
            vei_punkter = polyline.decode(route_res['routes'][0]['overview_polyline']['points'])
            m = folium.Map(location=vei_punkter[0], zoom_start=6)
            folium.PolyLine(vei_punkter, color="#2196F3", weight=5).add_to(m)

            temp_tabell = []
            akk_sek, akk_met, neste_sjekk_km, total_delay = 0, 0, 0, 0

            for step in leg['steps']:
                dist_km = akk_met / 1000
                if dist_km >= neste_sjekk_km:
                    passeringstid = avreise_dt + timedelta(seconds=akk_sek + (total_delay * 60))
                    lat, lon = step['start_location']['lat'], step['start_location']['lng']
                    
                    vaer = hent_vaer_detaljer(lat, lon, passeringstid)
                    kommune = hent_kommune(lat, lon)
                    hoyde = hent_hoyde(lat, lon)
                    opp, ned = hent_lysforhold(lat, lon, passeringstid)
                    
                    er_lyst = opp <= passeringstid.time() <= ned if opp else True
                    lys_tekst = "☀️ Lyst" if er_lyst else "🌙 Mørkt"
                    
                    score = 1
                    if not er_lyst: score += 1
                    if "Snø" in vaer['vaertype'] or "Sludd" in vaer['vaertype']: score += 4
                    if -1.0 <= vaer['temp'] <= 1.2: score += 3

                    folium.Marker(
                        location=[lat, lon],
                        popup=f"<b>{neste_sjekk_km} km: {kommune}</b><br>{vaer['vaertype']}<br>{vaer['nedbor']} mm",
                        icon=folium.Icon(color='black' if not er_lyst else 'blue', icon='info-sign')
                    ).add_to(m)

                    temp_tabell.append({
                        "KM": int(neste_sjekk_km),
                        "Sted": kommune,
                        "Passering": passeringstid.strftime("%H:%M"),
                        "Værtype": vaer['vaertype'],
                        "Lys": lys_tekst,
                        "Nedbør (mm)": vaer['nedbor'],
                        "Temp": f"{vaer['temp']}°C",
                        "Vind (Kast)": f"{vaer['vind']} ({vaer['kast']})",
                        "Høyde": hoyde,
                        "Risiko": score
                    })
                    total_delay += (5 if score >= 7 else 0)
                    neste_sjekk_km += 50
                akk_met += step['distance']['value']
                akk_sek += step['duration']['value']

            st.session_state.tabell_data = temp_tabell
            st.session_state.kart_html = m._repr_html_()

# --- 6. VISNING ---
if st.session_state.get('tabell_data') is not None:
    st.subheader("🗺️ Reisekart (Sorte markører = mørke)")
    components.html(st.session_state.kart_html, height=500)
    
    st.subheader("📋 Detaljert Veiplan")
    df = pd.DataFrame(st.session_state.tabell_data)
    styler = df.style.apply(fargelegg_rader, axis=1).background_gradient(subset=['Risiko'], cmap='YlOrRd')
    st.dataframe(styler, use_container_width=True)
    
    st.subheader("📈 Høydeprofil (moh)")
    st.area_chart(df.set_index('KM')['Høyde'])
