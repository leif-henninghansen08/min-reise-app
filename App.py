import streamlit as st
import requests
import folium
from datetime import datetime, timedelta
import streamlit.components.v1 as components

# --- 1. OPPSETT ---
st.set_page_config(page_title="SikkerTur Pro", page_icon="🛡️", layout="wide")

# --- 2. SIKKER HENTING AV API-NØKKEL ---
try:
    API_KEY = st.secrets["google_maps_api_key"]
except Exception:
    st.error("API-nøkkel mangler i Secrets! Legg den til i Streamlit Cloud.")
    st.stop()

# --- 3. INITIALISER MINNE ---
if "kart_html" not in st.session_state:
    st.session_state.kart_html = None
if "tabell_data" not in st.session_state:
    st.session_state.tabell_data = None
if "reise_tekst" not in st.session_state:
    st.session_state.reise_tekst = None

# --- 4. HJELPEFUNKSJONER ---
def hent_stedsnavn(lat, lon):
    url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lon}&key={API_KEY}&language=no&result_type=locality"
    try:
        res = requests.get(url).json()
        return res['results'][0]['address_components'][0]['long_name'] if res['status'] == 'OK' else "Vei"
    except: return "Norge"

def finn_ladestasjoner(lat, lon):
    url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={lat},{lon}&radius=5000&type=electric_vehicle_charging_station&key={API_KEY}"
    try:
        res = requests.get(url).json()
        return [p['name'] for p in res['results'][:2]] if res['status'] == 'OK' else []
    except: return []

def hent_vaer(lat, lon, tid):
    headers = {'User-Agent': 'SikkerTurApp/40.0'}
    # Merk: Yr bruker lat,lon (ikke lon,lat) i URL-oppsettet for compact
    url = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={lat}&lon={lon}"
    try:
        r = requests.get(url, headers=headers).json()
        v = min(r['properties']['timeseries'], key=lambda x: abs((datetime.fromisoformat(x['time'].replace('Z', '+00:00')) - tid.replace(tzinfo=None)).total_seconds()))
        d = v['data']['instant']['details']
        temp = d['air_temperature']
        nb = v['data'].get('next_1_hours', {}).get('details', {}).get('precipitation_amount', 0)
        vind = d['wind_speed']
        return temp, nb, vind
    except: return 0, 0, 0

def beregn_risiko(temp, nb, vind):
    score = 0
    info = []
    if -1.5 <= temp <= 0.5: score += 5; info.append("Isfare")
    elif temp < -1.5: score += 3; info.append("Vinterføre")
    if nb > 0.1: score += 3; info.append("Nedbør")
    if vind > 12: score += 2; info.append("Mye vind")
    score = min(score, 10)
    status = "🔴" if score >= 7 else "🟡" if score >= 4 else "🟢"
    return score, status, ", ".join(info) if info else "Lave risiko"

# --- 5. SIDEBAR ---
with st.sidebar:
    st.header("Planlegg din reise")
    fra = st.text_input("Fra:", "Sandnessjøen")
    til = st.text_input("Til:", "Trondheim")
    dato = st.date_input("Dato:", datetime.now())
    tid_v = st.time_input("Tid:", datetime.now())
    start_knapp = st.button("Start Full Analyse", type="primary")

# --- 6. LOGIKK VED TRYKK PÅ KNAPP ---
if start_knapp:
    with st.spinner('Henter vær, lading og veiforhold...'):
        avreise_dt = datetime.combine(dato, tid_v)
        url = f"https://maps.googleapis.com/maps/api/directions/json?origin={fra}&destination={til}&departure_time={int(avreise_dt.timestamp())}&key={API_KEY}&language=no"
        res = requests.get(url).json()

        if res['status'] == 'OK':
            leg = res['routes'][0]['legs'][0]
            st.session_state.reise_tekst = f"**Rute:** {leg['distance']['text']} | **Tid:** {leg['duration']['text']}"
            
            m = folium.Map(location=[leg['start_location']['lat'], leg['start_location']['lng']], zoom_start=6)
            temp_data = []
            akk_m, akk_s, neste_km = 0, 0, 0

            for step in leg['steps']:
                akk_m += step['distance']['value']
                akk_s += step['duration']['value']
                curr_km = akk_m / 1000

                if curr_km >= neste_km:
                    ankomst = avreise_dt + timedelta(seconds=akk_s)
                    lat, lon = step['end_location']['lat'], step['end_location']['lng']
                    
                    # Hent alle data
                    temp, nb, vind = hent_vaer(lat, lon, ankomst)
                    score, status, risiko_info = beregn_risiko(temp, nb, vind)
                    sted = hent_stedsnavn(lat, lon)
                    ladere = finn_ladestasjoner(lat, lon)
                    kamera = f"https://www.vegvesen.no/trafikk/kamera?lat={lat}&lon={lon}"
                    
                    # Kart-markør
                    farge = 'red' if score >= 7 else 'orange' if score >= 4 else 'green'
                    lader_txt = f"<br>⚡ {', '.join(ladere)}" if ladere else ""
                    popup_html = f"<b>{sted}</b><br>Tid: {ankomst.strftime('%H:%M')}<br>Vær: {temp}°C, {vind} m/s<br><b>Risiko: {score}/10</b> ({risiko_info}){lader_txt}<br><a href='{kamera}' target='_blank'>Se Vegkamera</a>"
                    
                    folium.Marker(
                        [lat, lon],
                        popup=folium.Popup(popup_html, max_width=250),
                        icon=folium.Icon(color=farge, icon='info-sign')
                    ).add_to(m)
                    
                    temp_data.append({
                        "KM": round(curr_km),
                        "Tid": ankomst.strftime('%H:%M'),
                        "Sted": sted,
                        "Temp": f"{temp}°C",
                        "Forhold": f"{status} {risiko_info}",
                        "Lading": ", ".join(ladere) if ladere else "Ingen nære"
                    })
                    neste_km += 75 # Sjekker hver 75. km

            st.session_state.tabell_data = temp_data
            st.session_state.kart_html = m._repr_html_()
        else:
            st.error("Kunne ikke finne rute. Sjekk stedsnavn.")

# --- 7. VISNING ---
if st.session_state.kart_html:
    st.markdown(st.session_state.reise_tekst)
    components.html(st.session_state.kart_html, height=500)
    st.subheader("Detaljert oversikt per etappe")
    st.dataframe(st.session_state.tabell_data, use_container_width=True)
else:
    st.info("Velg rute til venstre for å starte analysen.")
