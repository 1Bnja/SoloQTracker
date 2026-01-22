# Prueba de Caché

## 1. Iniciar la API
```bash
cd api
uvicorn index:app --reload
```

## 2. Primera llamada (genera datos)
```bash
curl http://localhost:8000/api/ranking
```
**Esperado**: Debería tardar ~2-5 segundos
**Logs**: Verás muchos "💾 GUARDADO EN CACHÉ"

## 3. Segunda llamada (usa caché)
```bash
curl http://localhost:8000/api/ranking
```
**Esperado**: Respuesta instantánea (<100ms)
**Logs**: "📦 CACHÉ HIT (Memoria): ranking:full"

## 4. Ver estadísticas
```bash
curl http://localhost:8000/api/cache/stats
```

## 5. Esperar 30 segundos y volver a llamar
```bash
# Espera 30 segundos...
curl http://localhost:8000/api/ranking
```
**Esperado**: Volverá a tardar porque el caché expiró
**Logs**: "❌ CACHÉ MISS" → regenera todo
