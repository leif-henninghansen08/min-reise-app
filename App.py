import streamlit as st
import requests
import folium
from datetime import datetime, timedelta
import streamlit.components.v1 as components

# --- 1. OPPSETT ---
st.set_page_config(page_title="SikkerTur Pro v6", page_icon="🚗", layout="wide")

# --- 2. SIKKER HENTING AV API-NØKKEL ---
try:
    API_KEY = st.secrets["google_maps_api_key"]
except:
    st.error("API-nøkkel mangler i Secrets!")
    st.stop()

# --- 3. INITIALISER MINNE ---
if "kart_html" not in st.session_state:
    st.session_state.kart_html = None
if "tabell_data" not in st.session_state:
    st.session_state.tabell_data = None

# --- 4. FUNKSJONER ---

def hent_stedsnavn(lat, lon):
    url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lon}&key={API_KEY}&language=no&result_type=locality|administrative_area_level_2"
    try:
        res = requests.get(url).json()
        if res['status'] == 'OK':
            return res['results'][0]['address_components'][0]['long_name']
    except: pass
    return f"{round(lat,2)}, {round(lon,2)}"

def hent_vaer(lat, lon, tid):
    headers = {'User-Agent': 'SikkerTurApp/v6.0'}
    url = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={round(lat, 4)}&lon={round(lon, 4)}"
    try:
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            data = r.json()
            target_time = tid.replace(tzinfo=None)
            best_match = min(data['properties']['timeseries'], 
                             key=lambda x: abs((datetime.fromisoformat(x['time'].replace('Z', '')) - target_time).total_seconds()))
            details = best_match['data']['instant']['details']
            return details['air_temperature'], details['wind_speed']
    except: return None, None
    return None, None

def tolke_forhold(temp):
    if temp is None: return "⚪ Ukjent", "gray"
    if -2 <= temp <= 1: return "🔴 Fare for glatt vei", "red"
    if temp < -2: return "🟡 Vinterføre", "orange"
    return "🟢 Gode forhold", "green"

# --- 5. SIDEBAR ---
with st.sidebar:
    st.header("Planlegg reisen")
    fra = st.text_input("Fra:", "Oslo")
    til = st.text_input("Til:", "Trondheim")
    dato = st.date_input("Dato", datetime.now())
    tid_v = st.time_input("Tid", datetime.now())
    start_knapp = st.button("Start Analyse", type="primary")

# --- 6. HOVEDLOGIKK ---
if start_knapp:
    with st.spinner('Beregner rute og henter vær...'):
        avreise_dt = datetime.combine(dato, tid_v)
        route_url = f"https://maps.googleapis.com/maps/api/directions/json?origin={fra}&destination={til}&departure_time={int(avreise_dt.timestamp())}&key={API_KEY}&language=no"
        route_res = requests.get(route_url).json()

        if route_res['status'] == 'OK':
            leg = route_res['routes'][0]['legs'][0]
            
            # Lag kartet
            m = folium.Map(location=[leg['start_location']['lat'], leg['start_location']['lng']], zoom_start=6)
            
            # --- NYTT: TEGNE RUTEN ---
            # Vi henter alle punkter fra ruten for å tegne den blå linjen
            rute_punkter = []
            for step in leg['steps']:
                rute_punkter.append([step['start_location']['lat'], step['start_location']['lng']])
            rute_punkter.append([leg['end_location']['lat'], leg['end_location']['lng']])
            
            folium.PolyLine(rute_punkter, color="blue", weight=5, opacity=0.8).add_to(m)
            # Zoomer kartet automatisk slik at hele linjen passer inn
            m.fit_bounds(rute_punkter)
            # --------------------------

            temp_tabell = []
            akk_s = 0
            steps = leg['steps']
            interval = max(1, len(steps) // 8)
            
            for i in range(0, len(steps), interval):
                step = steps[i]
                akk_s += step['duration']['value']
                ankomst = avreise_dt + timedelta(seconds=akk_s)
                lat, lon = step['end_location']['lat'], step['end_location']['lng']
                
                temp, vind = hent_vaer(lat, lon, ankomst)
                stedsnavn = hent_stedsnavn(lat, lon)
                status_tekst, farge = tolke_forhold(temp)
                
                vegvesen_url = f"https://www.vegvesen.no/trafikkinformasjon/reiseinformasjon/trafikkmeldinger?lat={lat}&lon={lon}&zoom=11"
                
                popup_txt = f"<b>{stedsnavn}</b><br>Passering: {ankomst.strftime('%H:%M')}<br>Vær: {temp}°C<br><a href='{vegvesen_url}' target='_blank'>Kamera</a>"
                folium.Marker([lat, lon], popup=folium.Popup(popup_txt, max_width=200), icon=folium.Icon(color=farge)).add_to(m)
                
                temp_tabell.append({
                    "Forventet Passering": ankomst.strftime('%H:%M'),
                    "Sted": stedsnavn,
                    "Temp": f"{temp}°C" if temp is not None else "N/A",
                    "Forhold": status_tekst
                })

            st.session_state.tabell_data = temp_tabell
            st.session_state.kart_html = m._repr_html_()
            st.session_state.reise_info = f"**Distanse:** {leg['distance']['text']} | **Reisetid:** {leg['duration']['text']}"

# --- 7. VISNING ---
if st.session_state.kart_html:
    st.markdown(st.session_state.reise_info)
    components.html(st.session_state.kart_html, height=500)
    st.dataframe(st.session_state.tabell_data, use_container_width=True)
