// Утилиты для профильной кнопки TopBarV3 (вынесены из компонента, чтобы не
// ломать react-refresh: файл компонента должен экспортировать только компоненты).

export function accountInfo(
  me?: { profile?: { avatar_url?: string | null; display_name?: string | null; first_name?: string | null; username?: string | null } | null } | null,
): { avatarUrl: string | null; userLabel: string | null; initials: string | null } {
  const p = me?.profile
  const name = p?.display_name || p?.first_name || p?.username || null
  return {
    avatarUrl: p?.avatar_url || null,
    userLabel: name,
    initials: name ? name.trim().slice(0, 1).toUpperCase() : null,
  }
}
