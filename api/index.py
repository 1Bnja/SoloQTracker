from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx
import asyncio
import os
import json
from collections import Counter
import tempfile
import time

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
KV_URL = os.environ.get("KV_URL") or os.environ.get("REDIS_URL")
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
            if data:
                print(f"📦 CACHÉ HIT (Redis): {key}")
                return json.loads(data)
            else:
                print(f"❌ CACHÉ MISS (Redis): {key}")
                return None
        except Exception as e:
            print(f"⚠️ Error Redis: {e}")
            return None
    
    # Fallback: usar /tmp en Vercel (persiste ~5 min entre requests)
    try:
        cache_file = os.path.join(tempfile.gettempdir(), f"lol_cache_{key.replace(':', '_').replace('/', '_')}.json")
        if os.path.exists(cache_file):
            # Verificar que no haya expirado (5 minutos)
            if time.time() - os.path.getmtime(cache_file) < 300:
                with open(cache_file, 'r') as f:
                    print(f"📦 CACHÉ HIT (Archivo): {key}")
                    return json.load(f)
            else:
                print(f"⏰ CACHÉ EXPIRADO (Archivo): {key}")
    except Exception as e:
        print(f"Error leyendo caché de archivo: {e}")
    
    # Memoria local
    if key in LOCAL_CACHE:
        print(f"📦 CACHÉ HIT (Memoria): {key}")
        return LOCAL_CACHE[key]
    
    print(f"❌ CACHÉ MISS (Todos): {key}")
    return None

async def set_cache(key: str, value: any, ttl: int = 300):
    """ttl en segundos (default 5 min)"""
    if redis_client:
        try:
            redis_client.setex(key, ttl, json.dumps(value))
            print(f"💾 GUARDADO EN CACHÉ (Redis): {key} (TTL: {ttl}s)")
        except Exception as e:
            print(f"⚠️ Error guardando en Redis: {e}")
    else:
        # Guardar en /tmp para persistir entre requests en Vercel
        try:
            cache_file = os.path.join(tempfile.gettempdir(), f"lol_cache_{key.replace(':', '_').replace('/', '_')}.json")
            with open(cache_file, 'w') as f:
                json.dump(value, f)
            print(f"💾 GUARDADO EN CACHÉ (Archivo): {key} (TTL: {ttl}s)")
        except Exception as e:
            print(f"Error escribiendo caché en archivo: {e}")
        LOCAL_CACHE[key] = value
        print(f"💾 GUARDADO EN CACHÉ (Memoria): {key}")

# Lista de amigos para trackear (Ejemplo)
AMIGOS = [
    {"nombre": "Tobio", "tag": "CHL"},
    {"nombre": "AintaxLsj", "tag": "2025"},
    {"nombre": "Freecss ツ", "tag": "HxH"},
    {"nombre": "Jamkkles", "tag": "LAS"},
    {"nombre": "Zoldyck ツ", "tag": "HxH"},
    {"nombre": "Zetter", "tag": "CHILE"},
    {"nombre": "Namelezz", "tag": "CHL"},
    {"nombre": "BlindWizard", "tag": "Miel"},
    {"nombre": "HølyDarkness", "tag": "Cool"},
    {"nombre": "b o r g", "tag": "404"},
    {"nombre": "R i v o t r i ł", "tag": "LAS"},
    {"nombre": "teas al dm", "tag": "shifu"},
]

# Semáforo para limitar concurrencia y no saturar la API key de desarrollo
# (Las keys de dev suelen permitir ~20 requests/segundo)
sem = asyncio.Semaphore(5)  # Reducido a 5 para mayor estabilidad

# Lock para evitar múltiples generaciones simultáneas del ranking
ranking_lock = asyncio.Lock()
ranking_in_progress = False

# Timeout global para todas las peticiones HTTP (10 segundos)
HTTP_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

async def fetch_riot(client: httpx.AsyncClient, url: str, retry_count: int = 0, max_retries: int = 3):
    async with sem:
        try:
            resp = await client.get(url, headers={"X-Riot-Token": RIOT_API_KEY}, timeout=HTTP_TIMEOUT)
            if resp.status_code == 429:
                if retry_count >= max_retries:
                    print(f"⚠️ Rate Limit máximo alcanzado después de {max_retries} intentos")
                    class RateLimitResponse:
                        status_code = 429
                        def json(self): return {}
                    return RateLimitResponse()
                
                # Backoff exponencial: 1s, 2s, 4s
                wait_time = 2 ** retry_count
                print(f"⚠️ Rate Limit. Esperando {wait_time}s... (intento {retry_count + 1}/{max_retries})")
                await asyncio.sleep(wait_time)
                return await fetch_riot(client, url, retry_count + 1, max_retries)
            return resp
        except httpx.TimeoutException:
            print(f"⏱️ Timeout en: {url[:100]}...")
            # Retornar una respuesta mock con status 504 para manejar timeout
            class TimeoutResponse:
                status_code = 504
                def json(self): return {}
            return TimeoutResponse()
        except Exception as e:
            print(f"❌ Error en fetch: {e}")
            class ErrorResponse:
                status_code = 500
                def json(self): return {}
            return ErrorResponse()

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

@app.get("/api/cache/stats")
async def cache_stats():
    """Endpoint de diagnóstico para verificar el estado del caché"""
    stats = {
        "cache_type": "Redis" if redis_client else "Archivo/Memoria",
        "redis_connected": redis_client is not None,
        "local_cache_keys": len(LOCAL_CACHE),
        "temp_dir": tempfile.gettempdir(),
    }
    
    # Contar archivos de caché en /tmp
    try:
        cache_files = [f for f in os.listdir(tempfile.gettempdir()) if f.startswith("lol_cache_")]
        stats["cache_files_count"] = len(cache_files)
        stats["cache_files"] = cache_files[:10]  # Mostrar solo los primeros 10
    except Exception as e:
        stats["cache_files_error"] = str(e)
    
    # Verificar si existe el caché del ranking
    ranking_cached = await get_cache("ranking:full")
    stats["ranking_cached"] = ranking_cached is not None
    if ranking_cached:
        stats["ranking_players"] = len(ranking_cached)
    
    return stats

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
    global ranking_in_progress
    
    try:
        # CACHÉ DEL RANKING COMPLETO (30 segundos)
        # Esto evita que múltiples usuarios saturen la API al mismo tiempo
        cache_key = "ranking:full"
        cached_ranking = await get_cache(cache_key)
        if cached_ranking:
            print("✅ Devolviendo ranking desde caché")
            return cached_ranking
        
        # Si la clave sigue siendo el placeholder, devolvemos datos falsos para probar el front
        if RIOT_API_KEY == "TU_CLAVE_DE_RIOT_AQUI":
            return [
                {"nombre": "DemoUser", "tag": "TEST", "rank": "Gold IV", "lp": 50, "winrate": 51.5, "en_partida": True, "puntos_totales": 1250},
                {"nombre": "SinApi", "tag": "KEY", "rank": "Challenger", "lp": 999, "winrate": 60.0, "en_partida": False, "puntos_totales": 4899},
            ]

        # SISTEMA DE LOCK: Solo permitir una generación a la vez
        # Si alguien más está generando, esperamos hasta 15 segundos
        try:
            async with asyncio.timeout(15):
                async with ranking_lock:
                    # Verificar de nuevo el caché por si otro proceso lo generó mientras esperábamos
                    cached_ranking = await get_cache(cache_key)
                    if cached_ranking:
                        print("✅ Otro proceso generó el ranking mientras esperábamos")
                        return cached_ranking
                    
                    ranking_in_progress = True
                    print("🔄 Generando ranking nuevo...")
                    # Lógica REAL de Riot
                    ranking = []
                    
                    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, limits=httpx.Limits(max_connections=5)) as client:
                        # 1. Obtener todos los PUUIDs en paralelo (o de caché)
                        tasks_puuid = [get_puuid(client, a['nombre'], a['tag']) for a in AMIGOS]
                        puuids = await asyncio.gather(*tasks_puuid)

                        # 2. Preparar tareas para obtener Rangos y Estado en Vivo
                        tasks_rank = []
                        tasks_live = []
                        amigos_validos = [] # Para mantener la relación índice-amigo

                        for i, puuid in enumerate(puuids):
                            if puuid:
                                # Tarea Rango
                                url_rank = f"https://{REGION_LEAGUE}.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}"
                                tasks_rank.append(fetch_riot(client, url_rank))
                                
                                # Tarea En Partida (Spectator V5 usa PUUID)
                                url_live = f"https://{REGION_LEAGUE}.api.riotgames.com/lol/spectator/v5/active-games/by-summoner/{puuid}"
                                tasks_live.append(fetch_riot(client, url_live))
                                
                                amigos_validos.append(AMIGOS[i])
                        
                        # Ejecutar todas las peticiones en paralelo
                        responses_rank = await asyncio.gather(*tasks_rank)
                        responses_live = await asyncio.gather(*tasks_live)

                        for i, res_rank in enumerate(responses_rank):
                            amigo = amigos_validos[i]
                            res_live = responses_live[i]
                            try:
                                
                                datos_jugador = {
                                    "nombre": amigo['nombre'], 
                                    "tag": amigo['tag'], 
                                    "rank": "Unranked", 
                                    "lp": 0, 
                                    "winrate": 0,
                                    "partidas": 0,
                                    "wins": 0,
                                    "losses": 0,
                                    "en_partida": False
                                }

                                # Procesar Rango
                                if res_rank.status_code == 200:
                                    colas_data = res_rank.json()
                                    for cola in colas_data:
                                        if cola["queueType"] == "RANKED_SOLO_5x5":
                                            wins = cola['wins']
                                            losses = cola['losses']
                                            total = wins + losses
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
                                            datos_jugador["wins"] = wins
                                            datos_jugador["losses"] = losses
                                
                                # Procesar Partida en Vivo (200 = En juego, 404 = No en juego)
                                if res_live.status_code == 200:
                                    datos_jugador["en_partida"] = True
                                
                                ranking.append(datos_jugador)
                                
                            except Exception as e:
                                print(f"Error con {amigo['nombre']}: {e}")

                    # Ordenar correctamente por tier, división y LP
                    for jugador in ranking:
                        tier = jugador.get('tier', 'IRON')
                        division = jugador.get('division', 'IV')
                        lp = jugador.get('lp', 0)
                        jugador['puntos_totales'] = calcular_puntos_totales(tier, division, lp)
                    
                    resultado_final = sorted(ranking, key=lambda x: x.get('puntos_totales', 0), reverse=True)
                    
                    # Guardar en caché por 60 segundos (aumentado de 30)
                    await set_cache("ranking:full", resultado_final, ttl=60)
                    ranking_in_progress = False
                    print("✅ Ranking generado y guardado en caché")
                    
                    return resultado_final
                    
        except asyncio.TimeoutError:
            # Si esperamos más de 15 segundos, devolver caché viejo si existe
            print("⚠️ Timeout esperando el lock, devolviendo caché viejo si existe")
            old_cache = await get_cache(cache_key)
            if old_cache:
                return old_cache
            return {"error": "El servidor está ocupado, intenta de nuevo en unos segundos"}
            
    except Exception as e:
        ranking_in_progress = False
        print(f"❌ ERROR GENERAL EN /api/ranking: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}

@app.get("/api/jugador/{nombre}/{tag}")
async def get_jugador_detalle(nombre: str, tag: str):
    """Obtiene detalles de un jugador: campeón más jugado y duo más frecuente"""
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, limits=httpx.Limits(max_connections=5)) as client:
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