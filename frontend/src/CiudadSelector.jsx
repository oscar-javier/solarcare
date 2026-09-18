import { useEffect, useRef, useState } from 'react';

function CiudadSelector({ ciudades, value, onChange, onSelect, placeholder }) {
  const [abierto, setAbierto] = useState(false);
  const contenedorRef = useRef(null);
  const normalizar = (texto) =>
    texto.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
  const texto = normalizar(value);
  const sugerencias = texto
    ? ciudades
        .filter((ciudad) =>
          normalizar(`${ciudad.nombre} ${ciudad.departamento}`).includes(texto)
        )
      : ciudades.slice(0, 50);

  useEffect(() => {
    const cerrarAlHacerClickFuera = (event) => {
      if (!contenedorRef.current?.contains(event.target)) {
        setAbierto(false);
      }
    };
    document.addEventListener('mousedown', cerrarAlHacerClickFuera);
    return () => document.removeEventListener('mousedown', cerrarAlHacerClickFuera);
  }, []);

  return (
    <div ref={contenedorRef} className="relative">
      <input
        type="text"
        value={value}
        onFocus={() => setAbierto(true)}
        onChange={(e) => {
          onChange(e.target.value);
          setAbierto(true);
        }}
        placeholder={placeholder}
        required
        className="w-full px-4 py-2 rounded-lg bg-slate-700 text-white placeholder-slate-400 outline-none focus:ring-2 focus:ring-yellow-500"
      />
      {abierto && sugerencias.length > 0 && (
        <div className="absolute z-10 left-0 right-0 mt-1 max-h-48 overflow-y-auto rounded-lg bg-slate-700 border border-slate-600 shadow-lg">
          {sugerencias.map((ciudad) => (
            <button
              key={ciudad.id}
              type="button"
              onClick={() => {
                onChange(ciudad.nombre);
                onSelect?.(ciudad);
                setAbierto(false);
              }}
              className="block w-full px-4 py-2 text-left text-sm text-white hover:bg-slate-600"
            >
              {ciudad.nombre}
              <span className="ml-2 text-xs text-slate-400">{ciudad.departamento}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default CiudadSelector;