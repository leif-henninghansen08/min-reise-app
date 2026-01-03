import streamlit as st
import requests
import folium
import polyline
from datetime import datetime, timedelta
import streamlit.components.v1 as components

# --- 1. GRUNNLEGGENDE OPPSETT ---
st.set_page_config(page_title="SikkerTur Pro v10", page_icon="🚗", layout="wide")

# --- 2. SIKKER HENTING AV API-NØKKEL ---
try:
    API_KEY = st.secrets["google_maps_api_key"]
except Exception:
    st.error("API-nøkkel mangler! Legg til 'google_maps_api_key' i Streamlit Secrets.")
    st.stop()

# --- 3. INITIALISER SESSION STATE (Hukommelse) ---
if "kart_html" not in st.session_state:
    st.session_state.kart_html = None
if "tabell_data" not in st.session_state:
    st.session_state.tabell_data = None
if "reise_info" not in st.session_state:
    st.session_state.reise_info = None

# --- 4. HJELPEFUNKSJONER ---

def hent_vaer(lat, lon, tid):
    """Henter temperatur fra Yr for et spesifikt tidspunkt."""
    headers = {'User-Agent': 'SikkerTurApp/v10.0 (din.epost@eksempel.no)'}
    url = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={round(lat, 4)}&lon={round(lon, 4)}"
    try:
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            data = r.json()
            target_time = tid.replace(tzinfo=None)
            best_match = min(data['properties']['timeseries'], 
                             key=lambda x: abs((datetime.fromisoformat(x['time'].replace('Z', '')) - target_time).total_seconds()))
            return best_match['data']['instant']['details']['air_temperature']
    except: return None
    return None

def hent_hoyde(lat, lon):
    """Henter meter over havet fra Google Elevation API."""
    url = f"https://maps.googleapis.com/maps/api/elevation/json?locations={lat},{lon}&key={API_KEY}"
    try:
        res = requests.get(url, timeout=5).json()
        if res['status'] == 'OK':
            return round(res['results'][0]['elevation'])
    except: return 0
    return 0

def hent_stedsnavn(lat, lon):
    """Henter navnet på stedet fra Google Geocoding."""
    url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lon}&key={API_KEY}&language=no&result_type=locality"
    try:
        res = requests.get(url, timeout=5).json()
        if res['status'] == 'OK':
            return res['results'][0]['address_components'][0]['long_name']
    except: pass
    return f"{round(lat,2)}, {round(lon,2)}"

# --- 5. SIDEBAR (Meny som ikke forsvinner) ---
with st.sidebar:
    st.header("📍 Reiseplanlegger")
    fra = st.text_input("Reis fra:", "Oslo", key="input_fra")
    til = st.text_input("Reis til:", "Trondheim", key="input_til")
    dato = st.date_input("Dato for avreise:", datetime.now(), key="input_dato")
    tid_v = st.time_input("Tidspunkt:", datetime.now(), key="input_tid")
    st.divider()
    start_knapp = st.button("🚀 Start Reiseanalyse", type="primary")

# --- 6. HOVEDLOGIKK (Kjøres ved knappetrykk) ---
if start_knapp:
    with st.spinner('Analyserer ruten din...'):
        avreise_dt = datetime.combine(dato, tid_v)
        route_url = f"https://maps.googleapis.com/maps/api/directions/json?origin={fra}&destination={til}&departure_time={int(avreise_dt.timestamp())}&key={API_KEY}&language=no"
        route_res = requests.get(route_url).json()

        if route_res['status'] == 'OK':
            route = route_res['routes'][0]
            leg = route['legs'][0]
            
            # 1. Tegn nøyaktig vei
            vei_punkter = polyline.decode(route['overview_polyline']['points'])
            m = folium.Map(location=vei_punkter[0], zoom_start=6)
            folium.PolyLine(vei_punkter, color="#2196F3", weight=6, opacity=0.8).add_to(m)
            m.fit_bounds(vei_punkter)

            temp_tabell = []
            akk_sek, akk_met, neste_sjekk_km = 0, 0, 0

            # 2. Gå gjennom alle 'steps' for å finne 100km punkter
            for step in leg['steps']:
                if (akk_met / 1000) >= neste_sjekk_km:
                    ankomst = avreise_dt + timedelta(seconds=akk_sek)
                    lat, lon = step['start_location']['lat'], step['start_location']['lng']
                    
                    # Datainnsamling
                    temp = hent_vaer(lat, lon, ankomst)
                    hoyde = hent_hoyde(lat, lon)
                    sted = hent_stedsnavn(lat, lon)
                    
                    # Risiko-logikk
                    farge = "red" if (temp is not None and temp <= 1) else "green"
                    status = "🔴 Isfare" if farge == "red" else "🟢 Trygt"
                    
                    # Kart-markør
                    vegvesen_url = f"https://www.vegvesen.no/trafikkinformasjon/reiseinformasjon/trafikkmeldinger?lat={lat}&lon={lon}&zoom=11"
                    popup_html = f"<b>{sted}</b><br>{neste_sjekk_km} km | {hoyde} moh<br>Temp: {temp}°C kl. {ankomst.strftime('%H:%M')}<br><a href='{vegvesen_url}' target='_blank'>Åpne kamera</a>"
                    
                    folium.Marker(
                        [lat, lon], 
                        popup=folium.Popup(popup_html, max_width=200),
                        icon=folium.Icon(color=farge, icon='cloud' if hoyde > 600 else 'info-sign')
                    ).add_to(m)
                    
                    temp_tabell.append({
                        "Distanse": f"{neste_sjekk_km} km",
                        "Sted": sted,
                        "Høyde": f"{hoyde} moh",
                        "Temp": f"{temp}°C" if temp is not None else "N/A",
                        "Passering": ankomst.strftime('%H:%M'),
                        "Forhold": status
                    })
                    neste_sjekk_km += 100

                akk_met += step['distance']['value']
                akk_sek += step['duration']['value']

            # Lagre resultatene i "minnet" (Session State)
            st.session_state.tabell_data = temp_tabell
            st.session_state.kart_html = m._repr_html_()
            st.session_state.reise_info = f"### 🗺️ Rutedetaljer\n**Avstand:** {leg['distance']['text']} | **Estimert tid:** {leg['duration']['text']}"
        else:
            st.error(f"Kunne ikke finne rute: {route_res.get('status')}. Sjekk skrivemåten på stedene.")

# --- 7. VISNING (Henter fra minnet slik at det ikke forsvinner ved interaksjon) ---
if st.session_state.kart_html:
    st.markdown(st.session_state.reise_info)
    components.html(st.session_state.kart_html, height=500)
    
    st.subheader("📊 Analyse per 100 km (ved forventet passeringstid)")
    st.dataframe(st.session_state.tabell_data, use_container_width=True)
else:
    st.info("👋 Velkommen! Fyll inn reisedetaljene i menyen til venstre og trykk 'Start Reiseanalyse' for å se vær og veiforhold.")
