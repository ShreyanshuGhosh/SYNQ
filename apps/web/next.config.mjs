/** @type {import('next').NextConfig} */
const nextConfig = {
  transpilePackages: ["@synq/shared-types"],
  webpack: (config, { isServer }) => {
    if (!isServer) {
      // OTel packages pull in Node-only modules that don't exist in the
      // browser bundle. Replace them with empty stubs so webpack doesn't
      // error or warn.
      config.resolve.fallback = {
        ...config.resolve.fallback,
        fs: false,
        net: false,
        tls: false,
        dns: false,
        "require-in-the-middle": false,
        "@opentelemetry/instrumentation": false,
        "@opentelemetry/instrumentation-fetch": false,
        "@opentelemetry/auto-instrumentations-web": false,
      };
    }
    return config;
  },
};

export default nextConfig;
