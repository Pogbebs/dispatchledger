import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import {
  ApiError,
  api,
  type Customer,
  type OrderRow,
  type Product,
  type Site,
} from "../api";
import { useAuth } from "../auth";
import { Pill, day, gallons, money, price } from "../format";

const STATUSES = ["pending", "scheduled", "delivered", "cancelled"];

export default function Orders() {
  const { user } = useAuth();
  const canEdit = user?.role === "admin" || user?.role === "dispatcher";

  const [rows, setRows] = useState<OrderRow[]>([]);
  const [status, setStatus] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await api.orders(status || undefined));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load orders.");
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => {
    void load();
  }, [load]);

  async function cancel(id: string) {
    try {
      await api.cancelOrder(id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not cancel.");
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Orders</h1>
          <div className="subtle">
            {loading ? "Loading…" : `${rows.length} shown`}
          </div>
        </div>
        <div className="filters">
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          {canEdit && (
            <button
              className="btn"
              onClick={() => setShowForm((open) => !open)}
            >
              {showForm ? "Close" : "New order"}
            </button>
          )}
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="card">
        {showForm && canEdit && (
          <NewOrderForm
            onCreated={() => {
              setShowForm(false);
              void load();
            }}
            onError={setError}
          />
        )}

        <table>
          <thead>
            <tr>
              <th>Requested</th>
              <th>Customer</th>
              <th>Site</th>
              <th>Product</th>
              <th className="num">Gallons</th>
              <th className="num">Unit price</th>
              <th className="num">Value</th>
              <th>Status</th>
              {canEdit && <th />}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td className="num">{day(row.requested_date)}</td>
                <td>{row.customer_name}</td>
                <td className="truncate subtle">{row.site_address}</td>
                <td>{row.product_name}</td>
                <td className="num">{gallons(row.quantity_gal)}</td>
                <td className="num">{price(row.unit_price)}</td>
                <td className="num">
                  {money(
                    String(Number(row.quantity_gal) * Number(row.unit_price)),
                  )}
                </td>
                <td>
                  <Pill status={row.status} />
                </td>
                {canEdit && (
                  <td>
                    {row.status !== "delivered" &&
                      row.status !== "cancelled" && (
                        <button
                          className="btn btn-quiet btn-sm"
                          onClick={() => cancel(row.id)}
                        >
                          Cancel
                        </button>
                      )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>

        {!loading && rows.length === 0 && (
          <div className="empty">No orders match this filter.</div>
        )}
      </div>
    </>
  );
}

function NewOrderForm({
  onCreated,
  onError,
}: {
  onCreated: () => void;
  onError: (message: string) => void;
}) {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [sites, setSites] = useState<Site[]>([]);

  const [customerId, setCustomerId] = useState("");
  const [siteId, setSiteId] = useState("");
  const [productId, setProductId] = useState("");
  const [quantity, setQuantity] = useState("1000");
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    Promise.all([api.customers(), api.products()])
      .then(([c, p]) => {
        setCustomers(c);
        setProducts(p);
        if (c[0]) setCustomerId(c[0].id);
        if (p[0]) setProductId(p[0].id);
      })
      .catch(() => onError("Could not load the order form."));
  }, [onError]);

  // Sites belong to a customer, so the list reloads whenever it changes.
  useEffect(() => {
    if (!customerId) return;
    api
      .sites(customerId)
      .then((list) => {
        setSites(list);
        setSiteId(list[0]?.id ?? "");
      })
      .catch(() => onError("Could not load delivery sites."));
  }, [customerId, onError]);

  const selectedProduct = useMemo(
    () => products.find((p) => p.id === productId),
    [products, productId],
  );

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await api.createOrder({
        customer_id: customerId,
        site_id: siteId,
        product_id: productId,
        quantity_gal: Number(quantity).toFixed(2),
        requested_date: date,
      });
      onCreated();
    } catch (err) {
      onError(
        err instanceof ApiError ? err.message : "Could not create the order.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="form-grid" onSubmit={submit}>
      <div>
        <label htmlFor="customer">Customer</label>
        <select
          id="customer"
          value={customerId}
          onChange={(e) => setCustomerId(e.target.value)}
        >
          {customers.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label htmlFor="site">Delivery site</label>
        <select
          id="site"
          value={siteId}
          onChange={(e) => setSiteId(e.target.value)}
        >
          {sites.map((s) => (
            <option key={s.id} value={s.id}>
              {s.address}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label htmlFor="product">Product</label>
        <select
          id="product"
          value={productId}
          onChange={(e) => setProductId(e.target.value)}
        >
          {products.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label htmlFor="qty">
          Gallons
          {selectedProduct && (
            <span style={{ textTransform: "none", fontWeight: 400 }}>
              {" "}
              at {price(selectedProduct.current_price)}
            </span>
          )}
        </label>
        <input
          id="qty"
          type="number"
          min="1"
          step="1"
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          required
        />
      </div>

      <div>
        <label htmlFor="date">Requested date</label>
        <input
          id="date"
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          required
        />
      </div>

      <button className="btn" disabled={busy || !siteId}>
        {busy ? "Creating…" : "Create order"}
      </button>
    </form>
  );
}
