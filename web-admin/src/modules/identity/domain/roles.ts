export type Role = 'admin' | 'manager' | 'member';
// Presentation policy only. The server authorizes every operation independently.
export function canManage(role: Role | undefined): boolean { return role === 'admin' || role === 'manager'; }
