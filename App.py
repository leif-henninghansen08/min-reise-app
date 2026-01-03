import streamlit as st
import requests
import folium
from datetime import datetime, timedelta
import streamlit.components.v1 as components

# --- 1. OPPSETT ---
st.set_page_config(page_title="SikkerTur Pro v4", page_icon="🚗", layout="wide")

# --- 2. SIKKER HENTING AV API-NØKKEL ---
try:
    API_KEY = st.secrets["google_maps_api_key"]
except:
    st.error("API-nøkkel mangler i Secrets! Legg den til i Streamlit Cloud.")
    st.stop()

# --- 3. INITIALISER MINNE ---
if "kart_html" not in st.session_state:
    st.session_state.kart_html = None
if "tabell_data" not in st.session_state:
    st.session_state.tabell_data = None

# --- 4. FUNKSJONER ---

def hent_vaer(lat, lon, tid):
    # Yr krever nøyaktig format og unik User-Agent for å svare
    headers = {'User-Agent': 'SikkerTurApp/v4.0 (kontakt: din@epost.no)'}
    url = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={round(lat, 4)}&lon={round(lon, 4)}"
    try:
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            data = r.json()
            target_time = tid.replace(tzinfo=None)
            # Finn nærmeste time i varselet
            best_match = min(data['properties']['timeseries'], 
                             key=lambda x: abs((datetime.fromisoformat(x['time'].replace('Z', '')) - target_time).total_seconds()))
            
            details = best_match['data']['instant']['details']
            return details['air_temperature'], details['wind_speed']
    except Exception as e:
        return None, None
    return None, None

def finn_ladere(lat, lon):
    # Søker etter ladestasjoner i nærheten (3km radius)
    url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={lat},{lon}&radius=3000&keyword=ev+charging&key={API_KEY}"
    try:
        res = requests.get(url).json()
        if res['status'] == 'OK':
            return [p['name'] for p in res['results'][:2]]
    except: pass
    return []

def tolke_forhold(temp):
    if temp is None: return "⚪ Ukjent", "gray"
    if -2 <= temp <= 1: return "🔴 Fare for glatt vei (nullføre)", "red"
    if temp < -2: return "🟡 Vinterføre (snø/is)", "orange"
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
    with st.spinner('Henter vær og veidata...'):
        avreise_dt = datetime.combine(dato, tid_v)
        route_url = f"https://maps.googleapis.com/maps/api/directions/json?origin={fra}&destination={til}&departure_time={int(avreise_dt.timestamp())}&key={API_KEY}&language=no"
        route_res = requests.get(route_url).json()

        if route_res['status'] == 'OK':
            leg = route_res['routes'][0]['legs'][0]
            m = folium.Map(location=[leg['start_location']['lat'], leg['start_location']['lng']], zoom_start=6)
            
            temp_tabell = []
            akk_s = 0
            steps = leg['steps']
            # Plukker ut ca 8 punkter langs ruten for oversikt
            interval = max(1, len(steps) // 8)
            
            for i in range(0, len(steps), interval):
                step = steps[i]
                akk_s += step['duration']['value']
                ankomst = avreise_dt + timedelta(seconds=akk_s)
                lat, lon = step['end_location']['lat'], step['end_location']['lng']
                
                temp, vind = hent_vaer(lat, lon, ankomst)
                status_tekst, farge = tolke_forhold(temp)
                ladere = finn_ladere(lat, lon)
                
                # Vegvesenets trafikk-kart (fungerer alltid)
                vegvesen_url = f"https://www.vegvesen.no/trafikkinformasjon/reiseinformasjon/trafikkmeldinger?lat={lat}&lon={lon}&zoom=11"
                
                popup_txt = f"""
                <div style='width:200px'>
                    <b>Tid: {ankomst.strftime('%H:%M')}</b><br>
                    Temp: {temp if temp is not None else '?' }°C<br>
                    Forhold: {status_tekst}<br>
                    Lading: {', '.join(ladere) if ladere else 'Søk i kart'}<br>
                    <a href='{vegvesen_url}' target='_blank'>Se Kamera & Trafikkinfo</a>
                </div>
                """
                folium.Marker([lat, lon], popup=folium.Popup(popup_txt), icon=folium.Icon(color=farge)).add_to(m)
                
                temp_tabell.append({
                    "Tid": ankomst.strftime('%H:%M'),
                    "Sted": f"{round(lat,2)}, {round(lon,2)}",
                    "Temp": f"{temp}°C" if temp is not None else "N/A",
                    "Forhold": status_tekst,
                    "Ladeforslag": ", ".join(ladere) if ladere else "-"
                })

            st.session_state.tabell_data = temp_tabell
            st.session_state.kart_html = m._repr_html_()
            st.session_state.reise_info = f"**Distanse:** {leg['distance']['text']} | **Estimert tid:** {leg['duration']['text']}"

# --- 7. VISNING ---
if st.session_state.kart_html:
    st.markdown(st.session_state.reise_info)
    components.html(st.session_state.kart_html, height=500)
    st.subheader("Etappeoversikt")
    st.dataframe(st.session_state.tabell_data, use_container_width=True)
