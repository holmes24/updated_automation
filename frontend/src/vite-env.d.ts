/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_SHARED_API_KEY?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
