export function CreditRiskLink() {
  const url = import.meta.env.VITE_CREDIT_RISK_URL || "http://localhost:5173";
  return <a href={url} target="_blank" rel="noopener noreferrer" title="Abrir Credit Risk Platform en una nueva pestaña">Credit Risk Platform <span aria-hidden="true">↗</span></a>;
}
