import streamlit as st
import requests
import folium
from streamlit_folium import st_folium
from datetime import datetime, timedelta

# --- APP KONFIGURASJON ---
st.set_page_config(page_title="SikkerTur App", page_icon="🚗", layout="wide")

# --- API-NØKKEL ---
API_KEY = "AIzaSyBk2ZqtmrPjWeZc6eZiIPyZ5p4VuWsc1ww"

# --- INITIALISERING AV MINNE (Session State) ---
if "kart_objekt" not in st.session_state:
    st.session_state.kart_objekt = None
if "tur_data" not in st.session_state:
    st.session_state.tur_data = None
if "reise_info" not in st.session_state:
    st.session_state.reise_info = ""

# --- HJELPEFUNKSJONER ---
def hent_stedsnavn(lat, lon):
    url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lon}&key={API_KEY}&language=no&result_type=locality|administrative_area_level_2"
    try:
        res = requests.get(url).json()
        return res['results'][0]['address_components'][0]['long_name'] if res['status'] == 'OK' else "Vei"
    except: return "Norge"

def finn_ladestasjoner(lat, lon):
    url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={lat},{lon}&radius=5000&type=electric_vehicle_charging_station&key={API_KEY}"
    try:
        res = requests.get(url).json()
        return [p['name'] for p in res['results'][:3]] if res['status'] == 'OK' else []
    except: return []

def hent_vaer(lat, lon, tid):
    headers = {'User-Agent': 'SikkerTurApp/12.0'}
    url = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={lat}&lon={lon}"
    try:
        r = requests.get(url, headers=headers).json()
        v = min(r['properties']['timeseries'], key=lambda x: abs((datetime.fromisoformat(x['time'].replace('Z', '+00:00')) - tid.replace(tzinfo=None)).total_seconds()))
        d = v['data']['instant']['details']
        nb = v['data'].get('next_1_hours', {}).get('details', {}).get('precipitation_amount', 0)
        return d['air_temperature'], nb, d['wind_speed']
    except: return 0, 0, 0

def beregn_risiko(temp, nb, vind):
    score = 0
    info = []
    if -1.5 <= temp <= 0.5: score += 5; info.append("Svart is")
    elif temp < -1.5: score += 3; info.append("Vinterføre")
    if nb > 0.1: score += 3; info.append("Nedbør")
    if vind > 12: score += 2; info.append("Vind")
    score = min(score, 10)
    status = "🔴" if score >= 7 else "🟡" if score >= 4 else "🟢"
    return score, status, ", ".join(info) if info else "Godt føre"

# --- SIDEBAR OG INPUT ---
st.title("🛡️ SikkerTur: Reiseplanlegger")

with st.sidebar:
    st.header("Planlegg reisen")
    start = st.text_input("Fra:", "Sandnessjøen")
    slutt = st.text_input("Til:", "Trondheim")
    dato = st.date_input("Dato:", datetime.now())
    tid_valg = st.time_input("Tid:", datetime.now())
    planlegg_knapp = st.button("Analyser rute")

# --- HOVEDLOGIKK VED KLIKK ---
if planlegg_knapp:
    with st.spinner('Henter data og beregner risiko...'):
        avreise_dt = datetime.combine(dato, tid_valg)
        url = f"https://maps.googleapis.com/maps/api/directions/json?origin={start}&destination={slutt}&departure_time={int(avreise_dt.timestamp())}&key={API_KEY}&language=no"
        res = requests.get(url).json()

        if res['status'] == 'OK':
            leg = res['routes'][0]['legs'][0]
            st.session_state.reise_info = f"Avstand: {leg['distance']['text']} | Estimert reisetid: {leg['duration']['text']}"
            
            # Start posisjon for kartet
            start_coords = [leg['start_location']['lat'], leg['start_location']['lng']]
            m = folium.Map(location=start_coords, zoom_start=6)
            
            temp_tur_data = []
            akk_m, akk_s, neste_km = 0, 0, 0

            for step in leg['steps']:
                akk_m += step['distance']['value']
                akk_s += step['duration']['value']
                curr_km = akk_m / 1000

                if curr_km >= neste_km:
                    ankomst = avreise_dt + timedelta(seconds=akk_s)
                    lat, lon = step['end_location']['lat'], step['end_location']['lng']
                    
                    temp, nb, vind = hent_vaer(lat, lon, ankomst)
                    score, status, info = beregn_risiko(temp, nb, vind)
                    sted = hent_stedsnavn(lat, lon)
                    ladere = finn_ladestasjoner(lat, lon)
                    kamera_url = f"https://www.vegvesen.no/trafikk/kamera?lat={lat}&lon={lon}"
                    
                    # Legg til markør i kartet
                    farge = 'red' if score >= 7 else 'orange' if score >= 4 else 'green'
                    lader_html = f"<br>⚡ <b>Lading:</b> {', '.join(ladere)}" if ladere else ""
                    popup_content = f"<b>{sted}</b><br>Tid: {ankomst.strftime('%H:%M')}<br>Risiko: {score}/10<br>{info}{lader_html}<br><a href='{kamera_url}' target='_blank'>Åpne Vegkamera</a>"
                    
                    folium.Marker(
                        [lat, lon],
                        popup=folium.Popup(popup_content, max_width=250),
                        icon=folium.Icon(color=farge, icon='info-sign')
                    ).add_to(m)
                    
                    temp_tur_data.append({
                        "KM": round(curr_km),
                        "Tid": ankomst.strftime('%H:%M'),
                        "Sted": sted,
                        "Temp": f"{temp}°C",
                        "Risiko": f"{score}/10 {status}",
                        "Lading": ", ".join(ladere) if ladere else "-",
                        "Kamera": kamera_url
                    })
                    neste_km += 70 # Sjekker hver 70. km for bedre detaljer
            
            # Lagre til session state
            st.session_state.tur_data = temp_tur_data
            st.session_state.kart_objekt = m
        else:
            st.error("Kunne ikke finne ruten. Sjekk stedsnavn eller API-nøkkel.")

# --- VISUALISERING (Kjører alltid) ---
if st.session_state.kart_objekt:
    st.info(st.session_state.reise_info)
    
    # Tegn kartet (bruker en unik key for å hindre at det forsvinner)
    st_folium(st.session_state.kart_objekt, width="100%", height=500, key="hovedkart")
    
    st.subheader("Veimelding og risiko per etappe")
    # Vis tabell med klikkbare lenker for kamera
    st.write("Klikk på et punkt i kartet for detaljer, eller se tabellen under:")
    
    # Formaterer tabellen for penere visning i Streamlit
    st.dataframe(st.session_state.tur_data, use_container_width=True)
if knapp:
    res = hent_data(fra, til, tid)
    
    if res['status'] == 'OK':
        leg = res['routes'][0]['legs'][0]
        st.success(f"Rute funnet! Total distanse: {leg['distance']['text']}")
        
        # Lag kartet
        m = folium.Map(location=[65, 12], zoom_start=5)
        
        # Vi sjekker punkter hver 100km
        akk_m = 0
        neste_km = 0
        tabell_data = []

        for step in leg['steps']:
            akk_m += step['distance']['value']
            curr_km = akk_m / 1000
            
            if curr_km >= neste_km:
                lat, lon = step['end_location']['lat'], step['end_location']['lng']
                
                # Her ville vi kalt de andre funksjonene (Vær, Kamera, Lading)
                # For eksempelets skyld bruker vi faste verdier på været
                score, status = beregn_risiko(-1, 0.5) 
                
                # Legg til i kart
                folium.Marker(
                    [lat, lon],
                    popup=f"Punkt {round(curr_km)}km",
                    icon=folium.Icon(color="red" if score >= 7 else "green")
                ).add_to(m)
                
                tabell_data.append({
                    "KM": round(curr_km),
                    "Status": status,
                    "Risiko": f"{score}/10"
                })
                neste_km += 100

        # Vis kartet i appen
        st_folium(m, width=700, height=500)
        
        # Vis tabellen under kartet
        st.table(tabell_data)
    else:
        st.error("Kunne ikke finne ruten. Sjekk stedsnavn.")

