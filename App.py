import streamlit as st
import requests
import folium
from datetime import datetime, timedelta
import streamlit.components.v1 as components

# --- 1. OPPSETT ---
st.set_page_config(page_title="SikkerTur Pro v7", page_icon="🚗", layout="wide")

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
    headers = {'User-Agent': 'SikkerTurApp/v7.0'}
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
    with st.spinner('Beregner rute med punkter hver 100 km...'):
        avreise_dt = datetime.combine(dato, tid_v)
        route_url = f"https://maps.googleapis.com/maps/api/directions/json?origin={fra}&destination={til}&departure_time={int(avreise_dt.timestamp())}&key={API_KEY}&language=no"
        route_res = requests.get(route_url).json()

        if route_res['status'] == 'OK':
            leg = route_res['routes'][0]['legs'][0]
            m = folium.Map(location=[leg['start_location']['lat'], leg['start_location']['lng']], zoom_start=6)
            
            # Tegne den blå ruten
            rute_punkter = [[step['start_location']['lat'], step['start_location']['lng']] for step in leg['steps']]
            rute_punkter.append([leg['end_location']['lat'], leg['end_location']['lng']])
            folium.PolyLine(rute_punkter, color="blue", weight=5, opacity=0.8).add_to(m)
            m.fit_bounds(rute_punkter)

            temp_tabell = []
            akk_sekunder = 0
            akk_meter = 0
            neste_sjekk_km = 0  # Starter på 0 km, så 100, 200...

            for step in leg['steps']:
                distanse_meter = step['distance']['value']
                tid_sekunder = step['duration']['value']
                
                # Sjekk om dette steget i ruten passerer en 100 km grense
                if (akk_meter / 1000) >= neste_sjekk_km:
                    ankomst = avreise_dt + timedelta(seconds=akk_sekunder)
                    lat, lon = step['start_location']['lat'], step['start_location']['lng']
                    
                    temp, vind = hent_vaer(lat, lon, ankomst)
                    stedsnavn = hent_stedsnavn(lat, lon)
                    status_tekst, farge = tolke_forhold(temp)
                    
                    vegvesen_url = f"https://www.vegvesen.no/trafikkinformasjon/reiseinformasjon/trafikkmeldinger?lat={lat}&lon={lon}&zoom=11"
                    
                    popup_txt = f"<b>{stedsnavn}</b><br>{round(akk_meter/1000)} km kjørt<br>Passering: {ankomst.strftime('%H:%M')}<br>Vær: {temp}°C<br><a href='{vegvesen_url}' target='_blank'>Kamera</a>"
                    folium.Marker([lat, lon], popup=folium.Popup(popup_txt, max_width=200), icon=folium.Icon(color=farge)).add_to(m)
                    
                    temp_tabell.append({
                        "Distanse": f"{round(akk_meter/1000)} km",
                        "Forventet Passering": ankomst.strftime('%H:%M'),
                        "Sted": stedsnavn,
                        "Temp": f"{temp}°C" if temp is not None else "N/A",
                        "Forhold": status_tekst
                    })
                    
                    neste_sjekk_km += 100 # Sett neste sjekkpunkt til 100 km lenger frem

                akk_meter += distanse_meter
                akk_sekunder += tid_sekunder

            # Legg til sluttpunktet i tabellen uansett
            ankomst_slutt = avreise_dt + timedelta(seconds=leg['duration']['value'])
            temp_tabell.append({
                "Distanse": f"{round(leg['distance']['value']/1000)} km (Slutt)",
                "Forventet Passering": ankomst_slutt.strftime('%H:%M'),
                "Sted": til,
                "Temp": "-",
                "Forhold": "Ankomst"
            })

            st.session_state.tabell_data = temp_tabell
            st.session_state.kart_html = m._repr_html_()
            st.session_state.reise_info = f"**Total distanse:** {leg['distance']['text']} | **Total reisetid:** {leg['duration']['text']}"

# --- 7. VISNING ---
if st.session_state.kart_html:
    st.markdown(st.session_state.reise_info)
    components.html(st.session_state.kart_html, height=500)
    st.dataframe(st.session_state.tabell_data, use_container_width=True)
