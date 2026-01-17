from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx
import asyncio
import os
import json
from collections import Counter

app = FastAPI()

# Habilitar CORS para que el frontend (puerto 3000) pueda llamar al backend (puerto 8000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Permitir todos los orígenes para producción (o cambia esto por tu dominio de Vercel)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CONFIGURACIÓN ---
# Lo ideal es usar variables de entorno, pero para probar rápido pon tu Key aquí:
RIOT_API_KEY = os.environ.get("RIOT_API_KEY", "RGAPI-bec81743-609c-4b83-8ff1-8e71ee44e89d")
REGION_ACCOUNT = "americas"
REGION_LEAGUE = "la2" # LAS

# --- CACHÉ (Vercel KV / Redis) ---
# Si configuras Vercel KV, estas variables se inyectan automáticamente.
KV_URL = os.environ.get("KV_URL")
redis_client = None

if KV_URL:
    try:
        from redis import Redis
        redis_client = Redis.from_url(KV_URL)
        print("✅ Conectado a Vercel KV (Redis)")
    except ImportError:
        print("⚠️ KV_URL detectada pero falta librería 'redis'.")

# Caché local en memoria (fallback si no hay Redis, se borra al reiniciar)
LOCAL_CACHE = {}

async def get_cache(key: str):
    if redis_client:
        try:
            data = redis_client.get(key)
            return json.loads(data) if data else None
        except Exception:
            return None
    return LOCAL_CACHE.get(key)

async def set_cache(key: str, value: any, ttl: int = 300):
    """ttl en segundos (default 5 min)"""
    if redis_client:
        try:
            redis_client.setex(key, ttl, json.dumps(value))
        except Exception:
            pass
    else:
        LOCAL_CACHE[key] = value

# Lista de amigos para trackear (Ejemplo)
AMIGOS = [
    {"nombre": "Tobio", "tag": "CHL"},
    {"nombre": "AintaxLsj", "tag": "2025"},
    {"nombre": "Freecss ツ", "tag": "HxH"},
    {"nombre": "Jamkkles", "tag": "LAS"},
    {"nombre": "Zoldyck ツ", "tag": "HxH"},
    {"nombre": "Zetter", "tag": "CHILE"},
    {"nombre": "komboss", "tag": "boss"},
    {"nombre": "Namelezz", "tag": "CHL"},
    {"nombre": "BlindWizard", "tag": "Miel"},
]

# Semáforo para limitar concurrencia y no saturar la API key de desarrollo
# (Las keys de dev suelen permitir ~20 requests/segundo)
sem = asyncio.Semaphore(10)

async def fetch_riot(client: httpx.AsyncClient, url: str):
    async with sem:
        resp = await client.get(url, headers={"X-Riot-Token": RIOT_API_KEY})
        if resp.status_code == 429:
            print("⚠️ Rate Limit. Esperando 2s...")
            await asyncio.sleep(2)
            return await fetch_riot(client, url)
        return resp

def calcular_puntos_totales(tier, rank, lp):
    """
    Calcula puntos totales para ordenar correctamente por liga y LP.
    Cada tier tiene un valor base + división + LP
    """
    # Valores base por tier
    tier_valores = {
        "IRON": 0,
        "BRONZE": 400,
        "SILVER": 800,
        "GOLD": 1200,
        "PLATINUM": 1600,
        "EMERALD": 2000,
        "DIAMOND": 2400,
        "MASTER": 2800,
        "GRANDMASTER": 3200,
        "CHALLENGER": 3600
    }
    
    # Valores por división (IV=0, III=100, II=200, I=300)
    rank_valores = {
        "IV": 0,
        "III": 100,
        "II": 200,
        "I": 300
    }
    
    puntos_base = tier_valores.get(tier.upper(), 0)
    puntos_division = rank_valores.get(rank.upper(), 0) if rank.upper() in rank_valores else 300  # Master+ no tiene división
    
    return puntos_base + puntos_division + lp

@app.get("/")
def read_root():
    return {"status": "online", "message": "La API está funcionando. Ve a /api/ranking para ver los datos."}

async def get_puuid(client, nombre, tag):
    cache_key = f"puuid:{nombre}:{tag}"
    cached = await get_cache(cache_key)
    if cached:
        return cached

    url = f"https://{REGION_ACCOUNT}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{nombre}/{tag}"
    res = await fetch_riot(client, url)
    
    if res.status_code == 200:
        puuid = res.json().get("puuid")
        # El PUUID no cambia, lo guardamos por 30 días
        await set_cache(cache_key, puuid, ttl=2592000)
        return puuid
    return None

@app.get("/api/ranking")
async def get_ranking():
    try:
        # Si la clave sigue siendo el placeholder, devolvemos datos falsos para probar el front
        if RIOT_API_KEY == "TU_CLAVE_DE_RIOT_AQUI":
            return [
                {"nombre": "DemoUser", "tag": "TEST", "rank": "Gold IV", "lp": 50, "winrate": 51.5},
                {"nombre": "SinApi", "tag": "KEY", "rank": "Challenger", "lp": 999, "winrate": 60.0},
            ]

        # Lógica REAL de Riot
        ranking = []
        
        async with httpx.AsyncClient() as client:
            # 1. Obtener todos los PUUIDs en paralelo (o de caché)
            tasks_puuid = [get_puuid(client, a['nombre'], a['tag']) for a in AMIGOS]
            puuids = await asyncio.gather(*tasks_puuid)

            # 2. Preparar tareas para obtener Rangos
            tasks_rank = []
            amigos_validos = [] # Para mantener la relación índice-amigo

            for i, puuid in enumerate(puuids):
                if puuid:
                    url_rank = f"https://{REGION_LEAGUE}.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}"
                    tasks_rank.append(fetch_riot(client, url_rank))
                    amigos_validos.append(AMIGOS[i])
            
            # Ejecutar peticiones de rango en paralelo
            responses_rank = await asyncio.gather(*tasks_rank)

            for i, res_rank in enumerate(responses_rank):
                amigo = amigos_validos[i]
            try:
                
                datos_jugador = {
                    "nombre": amigo['nombre'], 
                    "tag": amigo['tag'], 
                    "rank": "Unranked", 
                    "lp": 0, 
                    "winrate": 0,
                    "partidas": 0
                }

                if res_rank.status_code == 200:
                    colas_data = res_rank.json()
                    for cola in colas_data:
                        if cola["queueType"] == "RANKED_SOLO_5x5":
                            wins = cola['wins']
                            total = wins + cola['losses']
                            wr = round((wins / total) * 100, 1) if total > 0 else 0
                            
                            tier = cola['tier']
                            rank = cola['rank']
                            lp = cola['leaguePoints']
                            
                            datos_jugador["rank"] = f"{tier} {rank}"
                            datos_jugador["lp"] = lp
                            datos_jugador["winrate"] = wr
                            datos_jugador["tier"] = tier
                            datos_jugador["division"] = rank
                            datos_jugador["partidas"] = total
                
                ranking.append(datos_jugador)
                
            except Exception as e:
                print(f"Error con {amigo['nombre']}: {e}")

        # Ordenar correctamente por tier, división y LP
        for jugador in ranking:
            tier = jugador.get('tier', 'IRON')
            division = jugador.get('division', 'IV')
            lp = jugador.get('lp', 0)
            jugador['puntos_totales'] = calcular_puntos_totales(tier, division, lp)
        
        return sorted(ranking, key=lambda x: x.get('puntos_totales', 0), reverse=True)
    except Exception as e:
        print(f"❌ ERROR GENERAL EN /api/ranking: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}

@app.get("/api/jugador/{nombre}/{tag}")
async def get_jugador_detalle(nombre: str, tag: str):
    """Obtiene detalles de un jugador: campeón más jugado y duo más frecuente"""
    try:
        async with httpx.AsyncClient() as client:
            # 1. Obtener PUUID (con caché)
            puuid = await get_puuid(client, nombre, tag)
            if not puuid:
                return {"error": "Jugador no encontrado"}
            
            # 2. Obtener últimas 20 partidas (reducido de 50 para optimizar en Vercel)
            # queue=420 es RANKED_SOLO_5x5
            url_matches = f"https://{REGION_ACCOUNT}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?queue=420&start=0&count=20"
            res_matches = await fetch_riot(client, url_matches)
            
            if res_matches.status_code != 200:
                return {"error": "No se pudo obtener historial"}
            
            match_ids = res_matches.json()
            
            # 3. Analizar las partidas (Concurrente y con caché)
            campeones = {}
            duos = {}
            total_kills = 0
            total_deaths = 0
            total_assists = 0
            partidas_analizadas = 0
            temporada_2026_start = 1735689600000

            # Función auxiliar para obtener detalle de una partida
            async def get_match_data(mid):
                # Intentar sacar de caché (las partidas terminadas no cambian)
                cache_key = f"match:{mid}"
                cached_match = await get_cache(cache_key)
                if cached_match:
                    return cached_match
                
                # Si no está, pedir a Riot
                url = f"https://{REGION_ACCOUNT}.api.riotgames.com/lol/match/v5/matches/{mid}"
                r = await fetch_riot(client, url)
                if r.status_code == 200:
                    data = r.json()
                    # Guardar en caché por mucho tiempo (30 días)
                    await set_cache(cache_key, data, ttl=2592000)
                    return data
                return None

            # Lanzar todas las peticiones de partidas a la vez
            match_tasks = [get_match_data(mid) for mid in match_ids]
            matches_data = await asyncio.gather(*match_tasks)

            for match_data in matches_data:
                if not match_data: continue

                info = match_data.get("info", {})
                
                # Verificar temporada y cola
                if info.get("gameCreation", 0) < temporada_2026_start: continue
                if info.get("queueId", 0) != 420: continue
                
                participants = info.get("participants", [])
                
                # Buscar al jugador
                jugador_data = next((p for p in participants if p.get("puuid") == puuid), None)
                if not jugador_data: continue
                
                partidas_analizadas += 1
                
                # Estadísticas
                total_kills += jugador_data.get("kills", 0)
                total_deaths += jugador_data.get("deaths", 0)
                total_assists += jugador_data.get("assists", 0)
                
                # Campeón
                champ_name = jugador_data.get("championName")
                win = jugador_data.get("win", False)
                
                if champ_name not in campeones:
                    campeones[champ_name] = {"wins": 0, "games": 0, "kills": 0, "deaths": 0, "assists": 0}
                c = campeones[champ_name]
                c["games"] += 1
                c["kills"] += jugador_data.get("kills", 0)
                c["deaths"] += jugador_data.get("deaths", 0)
                c["assists"] += jugador_data.get("assists", 0)
                if win: c["wins"] += 1
                
                # Duo
                team_id = jugador_data.get("teamId")
                for p in participants:
                    if p.get("teamId") == team_id and p.get("puuid") != puuid:
                        duo_puuid = p.get("puuid")
                        if duo_puuid not in duos:
                            duos[duo_puuid] = {"nombre": f"{p.get('riotIdGameName')}#{p.get('riotIdTagline')}", "wins": 0, "games": 0}
                        duos[duo_puuid]["games"] += 1
                        if win: duos[duo_puuid]["wins"] += 1
            
            # Calcular KDA general
            kda_general = round((total_kills + total_assists) / total_deaths, 2) if total_deaths > 0 else round(total_kills + total_assists, 2)
            
            # Top Campeón
            top_champ = None
            if campeones:
                top_champ_name = max(campeones, key=lambda x: campeones[x]["games"])
                stats = campeones[top_champ_name]
                wr = round((stats["wins"] / stats["games"]) * 100, 1)
                kda_champ = round((stats["kills"] + stats["assists"]) / stats["deaths"], 2) if stats["deaths"] > 0 else round(stats["kills"] + stats["assists"], 2)
                top_champ = {
                    "nombre": top_champ_name,
                    "partidas": stats["games"],
                    "winrate": wr,
                    "kda": kda_champ
                }
            
            # Top Duo
            top_duo = None
            if duos:
                top_duo_puuid = max(duos, key=lambda x: duos[x]["games"])
                stats = duos[top_duo_puuid]
                # Solo mostrar si han jugado más de 1 partida juntos para filtrar randoms
                if stats["games"] > 1:
                    wr = round((stats["wins"] / stats["games"]) * 100, 1)
                    top_duo = {
                        "nombre": stats["nombre"],
                        "partidas": stats["games"],
                        "winrate": wr
                    }
            
            return {
                "campeon": top_champ,
                "duo": top_duo,
                "kda_general": kda_general,
                "partidas_temporada": partidas_analizadas
            }
        
    except Exception as e:
        print(f"❌ Error obteniendo detalles de {nombre}#{tag}: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}