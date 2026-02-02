'use client'; // Necesario porque usamos useEffect para pedir datos

import { useEffect, useState, useMemo } from 'react';
import React from 'react';

interface Jugador {
  nombre: string;
  tag: string;
  rank: string;
  lp: number;
  winrate: number;
  partidas: number;
  wins: number;
  losses: number;
  en_partida: boolean;
  puntos_totales?: number;
}

interface JugadorDetalle {
  campeon: {
    nombre: string;
    partidas: number;
    winrate: number;
    kda: number;
  } | null;
  duo: {
    nombre: string;
    partidas: number;
    winrate: number;
  } | null;
  kda_general: number;
  partidas_temporada: number;
}

export default function Home() {
  const [jugadores, setJugadores] = useState<Jugador[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandido, setExpandido] = useState<string | null>(null);
  const [detalles, setDetalles] = useState<{ [key: string]: JugadorDetalle }>({});
  const [loadingDetalle, setLoadingDetalle] = useState<string | null>(null);
  const [filtro, setFiltro] = useState('');
  const [orden, setOrden] = useState<{ campo: string; direccion: 'asc' | 'desc' }>({
    campo: 'puntos_totales', // Orden por defecto (Rango real)
    direccion: 'desc'
  });

  useEffect(() => {
    // Llamamos a nuestra API interna. Next.js redirige esto a Python.
    const controller = new AbortController();
    
    fetch('/api/ranking', { signal: controller.signal })
      .then(async (res) => {
        if (!res.ok) {
          throw new Error(`HTTP error! status: ${res.status}`);
        }
        const text = await res.text();
        try {
          return JSON.parse(text);
        } catch (e) {
          console.error("Respuesta no es JSON:", text);
          throw new Error("Respuesta inválida del servidor");
        }
      })
      .then((data) => {
        if (Array.isArray(data)) {
          setJugadores(data);
        } else {
          console.error("Data no es un array:", data);
          setJugadores([]);
        }
        setLoading(false);
      })
      .catch((err) => {
        if (err.name === 'AbortError') {
          console.log('Request cancelado');
        } else {
          console.error("Error cargando ranking:", err);
          setJugadores([]);
          setLoading(false);
        }
      });

    // Cleanup: cancelar request si el componente se desmonta
    return () => controller.abort();
  }, []);

  const handleExpandir = async (nombre: string, tag: string) => {
    const key = `${nombre}#${tag}`;
    
    // Si ya está expandido, colapsar
    if (expandido === key) {
      setExpandido(null);
      return;
    }
    
    // Expandir
    setExpandido(key);
    
    // Si ya tenemos los datos, no hacer la petición de nuevo
    if (detalles[key]) {
      return;
    }
    
    // Cargar detalles
    setLoadingDetalle(key);
    try {
      const res = await fetch(`/api/jugador/${encodeURIComponent(nombre)}/${encodeURIComponent(tag)}`);
      
      if (!res.ok) {
        console.error(`Error HTTP: ${res.status}`);
        throw new Error(`HTTP error! status: ${res.status}`);
      }
      
      const text = await res.text();
      let data;
      try {
        data = JSON.parse(text);
      } catch (e) {
        console.error("Respuesta no es JSON:", text);
        throw new Error("Respuesta inválida del servidor");
      }
      
      setDetalles(prev => ({ ...prev, [key]: data }));
    } catch (err) {
      console.error("Error cargando detalles:", err);
    } finally {
      setLoadingDetalle(null);
    }
  };

  const handleSort = (campo: string) => {
    setOrden(prev => ({
      campo,
      direccion: prev.campo === campo && prev.direccion === 'desc' ? 'asc' : 'desc'
    }));
  };

  const jugadoresFiltrados = useMemo(() => {
    let data = [...jugadores];

    // 1. Filtrar
    if (filtro) {
      const f = filtro.toLowerCase();
      data = data.filter(j => 
        j.nombre.toLowerCase().includes(f) || 
        j.tag.toLowerCase().includes(f)
      );
    }

    // 2. Ordenar
    data.sort((a, b) => {
      // Si ordenamos por 'rank', usamos 'puntos_totales' que viene del backend para mayor precisión
      const campoA = orden.campo === 'rank' ? (a.puntos_totales ?? 0) : (a as any)[orden.campo];
      const campoB = orden.campo === 'rank' ? (b.puntos_totales ?? 0) : (b as any)[orden.campo];

      if (typeof campoA === 'string' && typeof campoB === 'string') {
        return orden.direccion === 'asc' ? campoA.localeCompare(campoB) : campoB.localeCompare(campoA);
      }
      
      if (campoA < campoB) return orden.direccion === 'asc' ? -1 : 1;
      if (campoA > campoB) return orden.direccion === 'asc' ? 1 : -1;
      return 0;
    });

    return data;
  }, [jugadores, filtro, orden]);

  // Componente auxiliar para la flecha de orden
  const SortIcon = ({ active, dir }: { active: boolean; dir: 'asc' | 'desc' }) => (
    <span className={`ml-1 text-xs ${active ? 'text-blue-400' : 'text-slate-600'}`}>
      {active ? (dir === 'asc' ? '▲' : '▼') : '↕'}
    </span>
  );

  return (
    <main className="flex min-h-screen flex-col items-center p-8 bg-slate-950 text-slate-200">
      <div className="z-10 max-w-5xl w-full items-center justify-between font-mono text-sm">
        <h1 className="text-4xl font-bold text-center mb-8 bg-gradient-to-r from-blue-500 to-teal-400 bg-clip-text text-transparent">
          Solo Q Tracker
        </h1>

        {/* Barra de Búsqueda */}
        <div className="mb-6 flex justify-center">
          <div className="relative w-full max-w-md">
            <div className="absolute inset-y-0 left-0 flex items-center pl-3 pointer-events-none">
              <svg className="w-4 h-4 text-slate-500" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 20 20">
                <path stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="m19 19-4-4m0-7A7 7 0 1 1 1 8a7 7 0 0 1 14 0Z"/>
              </svg>
            </div>
            <input
              type="text"
              className="block w-full p-4 pl-10 text-sm border rounded-lg bg-slate-900 border-slate-700 placeholder-slate-400 text-white focus:ring-blue-500 focus:border-blue-500"
              placeholder="Buscar por nombre o tag..."
              value={filtro}
              onChange={(e) => setFiltro(e.target.value)}
            />
          </div>
        </div>

        {loading ? (
          <div className="flex justify-center mt-20">
            <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-blue-500"></div>
          </div>
        ) : (
          <div className="overflow-x-auto bg-slate-900 rounded-xl shadow-2xl border border-slate-800">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-slate-700 text-slate-400 uppercase text-xs tracking-wider">
                  <th className="p-4">#</th>
                  <th className="p-4 cursor-pointer hover:text-white select-none" onClick={() => handleSort('nombre')}>
                    <div className="flex items-center">Invocador <SortIcon active={orden.campo === 'nombre'} dir={orden.direccion} /></div>
                  </th>
                  <th className="p-4 cursor-pointer hover:text-white select-none" onClick={() => handleSort('rank')}>
                    <div className="flex items-center">Rango <SortIcon active={orden.campo === 'rank'} dir={orden.direccion} /></div>
                  </th>
                  <th className="p-4 cursor-pointer hover:text-white select-none" onClick={() => handleSort('lp')}>
                    <div className="flex items-center">LP <SortIcon active={orden.campo === 'lp'} dir={orden.direccion} /></div>
                  </th>
                  <th className="p-4 text-center cursor-pointer hover:text-white select-none" onClick={() => handleSort('partidas')}>
                    <div className="flex items-center justify-center">Partidas <SortIcon active={orden.campo === 'partidas'} dir={orden.direccion} /></div>
                  </th>
                  <th className="p-4 text-center">W/L</th>
                  <th className="p-4 text-center cursor-pointer hover:text-white select-none" onClick={() => handleSort('winrate')}>
                    <div className="flex items-center justify-center">Winrate <SortIcon active={orden.campo === 'winrate'} dir={orden.direccion} /></div>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {jugadoresFiltrados.length === 0 && (
                  <tr>
                    <td colSpan={7} className="p-8 text-center text-slate-500">
                      No se encontraron jugadores
                    </td>
                  </tr>
                )}
                {jugadoresFiltrados.map((j, index) => {
                  const key = `${j.nombre}#${j.tag}`;
                  const isExpanded = expandido === key;
                  const detalle = detalles[key];
                  
                  return (
                    <React.Fragment key={key}>
                      <tr 
                        className="hover:bg-slate-800 transition-colors duration-200 cursor-pointer"
                        onClick={() => handleExpandir(j.nombre, j.tag)}
                      >
                    <td className="p-4 font-bold text-slate-500">{index + 1}</td>
                    <td className="p-4 font-medium text-white">
                      <a 
                        href={`https://www.op.gg/summoners/las/${encodeURIComponent(j.nombre)}-${encodeURIComponent(j.tag)}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="hover:text-blue-400 transition-colors"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {j.nombre} <span className="text-slate-500 text-xs">#{j.tag}</span>
                      </a>
                      {j.en_partida && (
                        <span className="ml-2 inline-flex items-center gap-1.5 rounded-md bg-green-500/10 px-2 py-1 text-xs font-medium text-green-400 ring-1 ring-inset ring-green-500/20">
                          <span className="relative flex h-2 w-2">
                            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
                            <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
                          </span>
                          LIVE
                        </span>
                      )}
                    </td>
                    <td className="p-4">
                      <span className={`px-2 py-1 rounded text-xs font-bold border ${
                        j.rank.includes('Gold') ? 'bg-yellow-900/30 text-yellow-500 border-yellow-700' :
                        j.rank.includes('Platinum') ? 'bg-teal-900/30 text-teal-400 border-teal-700' :
                        j.rank.includes('Diamond') ? 'bg-blue-900/30 text-blue-400 border-blue-700' :
                        'bg-slate-700/50 text-slate-300 border-slate-600'
                      }`}>
                        {j.rank}
                      </span>
                    </td>
                    <td className="p-4 text-slate-300">{j.lp} LP</td>
                    <td className="p-4 text-center text-slate-300 font-medium">{j.partidas}</td>
                    <td className="p-4 text-center">
                      <span className="text-emerald-400 font-bold">{j.wins}</span>
                      <span className="text-slate-500 mx-1">/</span>
                      <span className="text-rose-400 font-bold">{j.losses}</span>
                    </td>
                    <td className="p-4">
                      <div className="flex flex-col items-center gap-1">
                        <span className={`text-xs font-bold ${j.winrate >= 50 ? 'text-emerald-400' : 'text-rose-400'}`}>
                          {j.winrate}%
                        </span>
                        <div className="w-24 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                          <div 
                            className={`h-full ${j.winrate >= 50 ? 'bg-emerald-500' : 'bg-rose-500'}`} 
                            style={{ width: `${j.winrate}%` }}
                          ></div>
                        </div>
                      </div>
                    </td>
                  </tr>
                  {/* Fila expandible con detalles */}
                  {isExpanded && (
                    <tr className="bg-slate-800/50">
                      <td colSpan={7} className="p-6">
                        {loadingDetalle === key ? (
                          <div className="flex justify-center py-4">
                            <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-blue-500"></div>
                          </div>
                        ) : detalle ? (
                          <div className="space-y-4">
                            {/* KDA General */}
                            <div className="bg-slate-900 rounded-lg p-4 border border-slate-700">
                              <h3 className="text-sm font-bold text-slate-400 mb-2 uppercase tracking-wider">
                                📊 Estadísticas de la temporada
                              </h3>
                              <div className="flex gap-6">
                                <div>
                                  <p className="text-slate-400 text-xs">KDA General</p>
                                  <p className={`text-2xl font-bold ${
                                    detalle.kda_general >= 3 ? 'text-emerald-400' : 
                                    detalle.kda_general >= 2 ? 'text-blue-400' : 
                                    'text-slate-300'
                                  }`}>
                                    {detalle.kda_general}
                                  </p>
                                </div>
                                <div>
                                  <p className="text-slate-400 text-xs">Partidas Analizadas</p>
                                  <p className="text-2xl font-bold text-slate-300">{detalle.partidas_temporada}</p>
                                </div>
                              </div>
                            </div>

                            <div className="grid grid-cols-2 gap-6">
                            {/* Campeón más jugado */}
                            <div className="bg-slate-900 rounded-lg p-4 border border-slate-700">
                              <h3 className="text-sm font-bold text-slate-400 mb-3 uppercase tracking-wider">
                                🏆 Campeón más jugado
                              </h3>
                              {detalle.campeon ? (
                                <div className="flex items-center gap-4">
                                  <img 
                                    src={`https://ddragon.leagueoflegends.com/cdn/14.1.1/img/champion/${detalle.campeon.nombre}.png`}
                                    alt={detalle.campeon.nombre}
                                    className="w-16 h-16 rounded-lg border-2 border-slate-600"
                                    onError={(e) => {
                                      e.currentTarget.src = 'https://ddragon.leagueoflegends.com/cdn/14.1.1/img/profileicon/29.png';
                                    }}
                                  />
                                  <div>
                                    <p className="font-bold text-white text-lg">{detalle.campeon.nombre}</p>
                                    <p className="text-slate-400 text-sm">{detalle.campeon.partidas} partidas</p>
                                    <div className="flex gap-3 mt-1">
                                      <p className={`font-bold text-sm ${detalle.campeon.winrate >= 50 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                        {detalle.campeon.winrate}% WR
                                      </p>
                                      <p className={`font-bold text-sm ${
                                        detalle.campeon.kda >= 3 ? 'text-emerald-400' : 
                                        detalle.campeon.kda >= 2 ? 'text-blue-400' : 
                                        'text-slate-300'
                                      }`}>
                                        {detalle.campeon.kda} KDA
                                      </p>
                                    </div>
                                  </div>
                                </div>
                              ) : (
                                <p className="text-slate-500 text-sm">Sin datos</p>
                              )}
                            </div>

                            {/* Duo más frecuente */}
                            <div className="bg-slate-900 rounded-lg p-4 border border-slate-700">
                              <h3 className="text-sm font-bold text-slate-400 mb-3 uppercase tracking-wider">
                                👥 Duo más frecuente
                              </h3>
                              {detalle.duo ? (
                                <div>
                                  <p className="font-bold text-white text-lg">{detalle.duo.nombre}</p>
                                  <p className="text-slate-400 text-sm">{detalle.duo.partidas} partidas juntos</p>
                                  <p className={`font-bold text-sm ${detalle.duo.winrate >= 50 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                    {detalle.duo.winrate}% WR
                                  </p>
                                </div>
                              ) : (
                                <p className="text-slate-500 text-sm">Sin duo frecuente</p>
                              )}
                            </div>
                          </div>
                          </div>
                        ) : (
                          <p className="text-slate-500 text-center">Error cargando datos</p>
                        )}
                      </td>
                    </tr>
                  )}
                </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </main>
  );
}