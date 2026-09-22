import { useEffect, useState } from "react";
import { ApiError, api, type Customer } from "../api";

export default function Customers() {
  const [rows, setRows] = useState<Customer[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .customers()
      .then(setRows)
      .catch((err) =>
        setError(
          err instanceof ApiError ? err.message : "Could not load customers.",
        ),
      )
      .finally(() => setLoading(false));
  }, []);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Customers</h1>
          <div className="subtle">
            {loading ? "Loading…" : `${rows.length} on the books`}
          </div>
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Email</th>
              <th>Phone</th>
              <th className="num">Terms</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>{row.name}</td>
                <td className="subtle truncate">{row.email ?? "—"}</td>
                <td className="subtle">{row.phone ?? "—"}</td>
                <td className="num">Net {row.payment_terms_days}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {!loading && rows.length === 0 && (
          <div className="empty">No customers yet.</div>
        )}
      </div>
    </>
  );
}
