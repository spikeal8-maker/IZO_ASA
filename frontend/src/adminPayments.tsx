export default function AdminPayments() {
  return (
    <div className="admin-section admin-payments-page">
      <div className="admin-section-head">
        <div>
          <h3>Платежи</h3>
          <p>Счета, оплаты, возвраты и начисление токенов.</p>
        </div>
      </div>
      <div className="admin-note">
        <strong>Подключение ЮKassa готовится</strong>
        <p>Страница отделена от CRM. Здесь будут общая сводка, журнал webhook, сверка и возвраты.</p>
      </div>
    </div>
  )
}
