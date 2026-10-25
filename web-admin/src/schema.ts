/** Phase 1 contract. Regenerate with openapi-typescript after make lock. */
export interface components {
  schemas: {
    Readiness: {
      status: 'ready' | 'degraded';
      services: Record<string, boolean>;
    };
    Health: {status?: 'ok'};
  };
}
