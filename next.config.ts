import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Esta parte es la magia para desarrollo local
  rewrites: async () => {
    return [
      {
        source: "/api/:path*",
        destination:
          process.env.NODE_ENV === "development"
            ? "http://127.0.0.1:8000/api/:path*" // En tu PC: Python corre en puerto 8000
            : "/api/",                            // En Vercel: Se encarga la nube
      },
    ];
  },
};

export default nextConfig;