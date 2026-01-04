import streamlit as st
import requests
import folium
import polyline
import pandas as pd
from datetime import datetime, timedelta
import streamlit.components.v1 as components
import math

# --- 1. KONFIGURASJON ---
st.set_page_config(page_title="SikkerTur Pro v22.6", page_icon="🚗", layout="wide")

# --- 2. INITIALISERING ---
if "tabell_data" not in st.session_state:
    st.session_state.tabell_data = None
if "kart_html" not in st.session_state:
    st.session_state.kart_html = None
if "maks_risiko" not in st.session_state:
    st.session_state.maks_risiko = 0

try:
    API_KEY = st.secrets["google_maps_api_key"]
except:
    st.error("API-nøkkel mangler i Streamlit Secrets!")
    st.stop()

# --- 3. HJELPEFUNKSJONER ---

def haversine_distance(p1, p2):
    R = 6371000 
    lat1, lon1 = math.radians(p1[0]), math.radians(p1[1])
    lat2, lon2 = math.radians(p2[0]), math.radians(p2[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1-a)))

def hent_lysforhold(lat, lon, dato):
    url = f"https://api.sunrise-sunset.org/json?lat={lat}&lng={lon}&date={dato.strftime('%Y-%m-%d')}&formatted=0"
    try:
        res = requests.get(url, timeout=5).json()
        if res['status'] == 'OK':
            opp = datetime.fromisoformat(res['results']['sunrise'].replace('Z', '+00:00')) + timedelta(hours=1)
            ned = datetime.fromisoformat(res['results']['sunset'].replace('Z', '+00:00')) + timedelta(hours=1)
            return opp.time(), ned.time()
    except: pass
    return None, None

def oversett_vaertype(symbol_kode):
    koder = {'clearsky': 'Klart vær', 'fair': 'Lettskyet', 'partlycloudy': 'Delvis skyet', 'cloudy': 'Overskyet', 'rain': 'Regn', 'heavyrain': 'Kraftig regn', 'snow': 'Snø', 'sleet': 'Sludd', 'fog': 'Tåke'}
    return koder.get(symbol_kode.split('_')[0], symbol_kode.capitalize())

def hent_vaer_detaljer(lat, lon, tid):
    headers = {'User-Agent': 'SikkerTurApp/v22.6'}
    url = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={round(lat, 4)}&lon={round(lon, 4)}"
    try:
        r = requests.get(url, headers=headers, timeout=5)
        data = r.json()
        target_time = tid.replace(tzinfo=None)
        best_match = min(data['properties']['timeseries'], key=lambda x: abs((datetime.fromisoformat(x['time'].replace('Z', '')) - target_time).total_seconds()))
        instant = best_match['data']['instant']['details']
        neste = best_match['data'].get('next_1_hours', {})
        return {
            "temp": instant.get('air_temperature', 0), "vind": instant.get('wind_speed', 0), 
            "kast": instant.get('wind_speed_of_gust', 0), "nedbor": neste.get('details', {}).get('precipitation_amount', 0), 
            "vaertype": oversett_vaertype(neste.get('summary', {}).get('symbol_code', 'clearsky_day'))
        }
    except: return {"temp": 0, "vind": 0, "kast": 0, "nedbor": 0, "vaertype": "Ukjent"}

def hent_kommune(lat, lon):
    url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lon}&key={API_KEY}&language=no"
    try:
        res = requests.get(url, timeout=5).json()
        for r in res['results']:
            for c in r['address_components']:
                if "administrative_area_level_2" in c['types']: return c['long_name']
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
    if 'Glatte veier' in str(row['Årsak til risiko']):
        styles[9] = 'background-color: #ff4b4b; color: white; font-weight: bold'
    if row['Lys'] == '🌙 Mørkt':
        styles[4] = 'background-color: #2c3e50; color: #ecf0f1'
    return styles

# --- 4. SIDEBAR ---
st.sidebar.header("📍 Reiseplanlegger Pro v22.6")
fra = st.sidebar.text_input("Fra:", value="Oslo")
til = st.sidebar.text_input("Til:", value="Trondheim")
valgt_dato = st.sidebar.date_input("Dato for avreise:", value=datetime.now())

# NYTT: Direkte tidstasting
tid_tekst = st.sidebar.text_input("Tidspunkt (TT:MM):", value=datetime.now().strftime("%H:%M"))

try:
    h, m_val = map(int, tid_tekst.split(':'))
    avreise_dt = datetime.combine(valgt_dato, datetime.min.time().replace(hour=h, minute=m_val))
except:
    st.sidebar.error("Bruk formatet TT:MM (f.eks. 08:30)")
    avreise_dt = datetime.now()

start_knapp = st.sidebar.button("🚀 Kjør Totalanalyse", type="primary")

# --- 5. LOGIKK ---
if start_knapp:
    with st.spinner('Analyserer rute, trafikk, vær og is-fare...'):
        avreise_ts = int(avreise_dt.timestamp())
        route_url = f"https://maps.googleapis.com/maps/api/directions/json?origin={fra}&destination={til}&departure_time={avreise_ts}&key={API_KEY}&language=no"
        route_res = requests.get(route_url).json()

        if route_res['status'] == 'OK':
            leg = route_res['routes'][0]['legs'][0]
            alle_punkter = polyline.decode(route_res['routes'][0]['overview_polyline']['points'])
            m = folium.Map(location=alle_punkter[0], zoom_start=6)
            folium.PolyLine(alle_punkter, color="#2196F3", weight=5).add_to(m)
            
            temp_tabell = []
            akk_meter, neste_sjekk_meter = 0, 0
            total_sekunder = leg.get('duration_in_traffic', leg['duration'])['value']
            maks_r = 0

            for i in range(len(alle_punkter) - 1):
                p1, p2 = alle_punkter[i], alle_punkter[i+1]
                dist_steg = haversine_distance(p1, p2)
                
                if akk_meter >= neste_sjekk_meter:
                    km_merke = int(neste_sjekk_meter / 1000)
                    framdrift = akk_meter / leg['distance']['value'] if leg['distance']['value'] > 0 else 0
                    passeringstid = avreise_dt + timedelta(seconds=total_sekunder * framdrift)
                    
                    lat, lon = p1[0], p1[1]
                    vaer = hent_vaer_detaljer(lat, lon, passeringstid)
                    kommune = hent_kommune(lat, lon)
                    hoyde = hent_hoyde(lat, lon)
                    opp, ned = hent_lysforhold(lat, lon, passeringstid)
                    
                    er_lyst = opp <= passeringstid.time() <= ned if opp else True
                    
                    # --- UTVIDET RISIKO-LOGIKK (v22.6) ---
                    score = 1
                    arsaker = []
                    
                    # Sjekk for glatte veier (Kombinasjon av nedbør og kulde)
                    if vaer['nedbor'] > 0 and vaer['temp'] <= 0.5:
                        score += 5; arsaker.append("Glatte veier (Is/Snø)")
                    elif -1.1 <= vaer['temp'] <= 1.1:
                        score += 2; arsaker.append("Nullføre")
                        
                    if not er_lyst: score += 1; arsaker.append("Mørke")
                    if vaer['vind'] > 12: score += 1; arsaker.append("Vind")
                    if hoyde > 800: score += 1; arsaker.append("Fjell")
                    if vaer['temp'] < -10: score += 1; arsaker.append("Sterk kulde")

                    if score > maks_r: maks_r = score
                    forklaring = ", ".join(arsaker) if arsaker else "Gode forhold"

                    temp_tabell.append({
                        "KM": km_merke, "Sted": kommune, "Passering": passeringstid.strftime("%H:%M"),
                        "Værtype": vaer['vaertype'], "Lys": "☀️ Lyst" if er_lyst else "🌙 Mørkt", 
                        "Nedbør": f"{vaer['nedbor']}mm", "Temp": f"{vaer['temp']}°C", 
                        "Vind": f"{vaer['vind']} ({vaer['kast']})", "Risiko": score, 
                        "Årsak til risiko": forklaring
                    })
                    
                    farge = 'red' if score >= 6 else 'black' if not er_lyst else 'blue'
                    folium.Marker([lat, lon], popup=f"{km_merke}km: {kommune}\n{forklaring}", icon=folium.Icon(color=farge)).add_to(m)
                    neste_sjekk_meter += 50000 
                
                akk_meter += dist_steg

            st.session_state.tabell_data = temp_tabell
            st.session_state.kart_html = m._repr_html_()
            st.session_state.maks_risiko = maks_r

# --- 6. VISNING ---
st.title("🚗 SikkerTur Pro")

if st.session_state.tabell_data:
    # SAMMENDRAGS-BOKS
    mr = st.session_state.maks_risiko
    if mr >= 7:
        st.error(f"⚠️ **HØY RISIKO ({mr}/10):** Vi har funnet partier med fare for glatte veier. Vurder å utsette reisen eller kjør svært forsiktig.")
    elif 4 <= mr < 7:
        st.warning(f"🔔 **MODERAT RISIKO ({mr}/10):** Turen har partier med mørke, vind eller nullføre. Vær oppmerksom.")
    else:
        st.success("✅ **LAV RISIKO:** Forholdene ser gode ut for din valgte reisetid. God tur!")

    components.html(st.session_state.kart_html, height=450)
    df = pd.DataFrame(st.session_state.tabell_data)
    st.dataframe(df.style.apply(fargelegg_rader, axis=1).background_gradient(subset=['Risiko'], cmap='YlOrRd'), use_container_width=True)
else:
    st.info("👋 Velkommen! Skriv inn reiseinfo til venstre. Tid tastes direkte (f.eks. 14:30).")
