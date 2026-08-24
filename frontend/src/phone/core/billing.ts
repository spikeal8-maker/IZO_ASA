export type PhoneTokenKind = 'daily' | 'main'

export type PhoneBillingQuote = {
  tokens: number
  tokenKind: PhoneTokenKind
  label: string
}

export function phoneTokenClass(kind: PhoneTokenKind): string {
  return kind === 'daily' ? 'phone-token phone-token--daily' : 'phone-token phone-token--main'
}

export function phoneBillingLabel(quote: PhoneBillingQuote): string {
  const amount = Math.max(0, Math.ceil(Number(quote.tokens) || 0))
  return `${amount} ${amount === 1 ? 'ток.' : 'ток.'} · ${quote.tokenKind === 'daily' ? 'дневные' : 'основные'}`
}
