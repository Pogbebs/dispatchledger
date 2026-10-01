import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ApiError, api, type Customer, type InviteCreated, type InviteRow } from "../api";
import { useAuth } from "../auth";
import { day } from "../format";

/**
 * Customers, and their access to the portal.
 *
 * Inviting lives here rather than on a settings page because this is where a
 * dispatcher is already looking when a customer asks to see their own orders.
 */
export default function Customers() {
  const { user } = useAuth();
  const canInvite = user?.role === "admin" || user?.role === "dispatcher";

  const [rows, setRows] = useState<Customer[]>([]);
  const [invites, setInvites] = useState<InviteRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [inviting, setInviting] = useState<Customer | null>(null);
  const [issued, setIssued] = useState<InviteCreated | null>(null);

  const load = useCallback(async () => {
    try {
      const [customers, pending] = await Promise.all([
        api.customers(),
        canInvite ? api.invites() : Promise.resolve([] as InviteRow[]),
      ]);
      setRows(customers);
      setInvites(pending);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load customers.");
    } finally {
      setLoading(false);
    }
  }, [canInvite]);

  useEffect(() => {
    void load();
  }, [load]);

  /** The most recent live invitation for a customer, if any. */
  function pendingFor(customerId: string): InviteRow | undefined {
    return invites.find(
      (i) => i.customer_id === customerId && i.status === "pending",
    );
  }

  function hasAccount(customerId: string): boolean {
    return invites.some(
      (i) => i.customer_id === customerId && i.status === "accepted",
    );
  }

  async function revoke(id: string) {
    try {
      await api.revokeInvite(id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not revoke that invite.");
    }
  }

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

      {issued && <InviteIssued invite={issued} onDone={() => setIssued(null)} />}

      <div className="card">
        {inviting && (
          <InviteForm
            customer={inviting}
            onIssued={(invite) => {
              setIssued(invite);
              setInviting(null);
              void load();
            }}
            onCancel={() => setInviting(null)}
            onError={setError}
          />
        )}

        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Email</th>
              <th>Phone</th>
              <th className="num">Terms</th>
              {canInvite && <th>Portal</th>}
              {canInvite && <th />}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const pending = pendingFor(row.id);
              return (
                <tr key={row.id}>
                  <td>{row.name}</td>
                  <td className="subtle truncate">{row.email ?? "—"}</td>
                  <td className="subtle">{row.phone ?? "—"}</td>
                  <td className="num">Net {row.payment_terms_days}</td>

                  {canInvite && (
                    <td className="subtle">
                      {hasAccount(row.id) ? (
                        <span className="pill pill-delivered">Active</span>
                      ) : pending ? (
                        <span className="pill pill-pending">
                          Invited · expires {day(pending.expires_at)}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                  )}

                  {canInvite && (
                    <td className="cell-actions">
                      {pending ? (
                        <button
                          className="btn btn-quiet btn-sm"
                          onClick={() => revoke(pending.id)}
                        >
                          Revoke
                        </button>
                      ) : hasAccount(row.id) ? null : (
                        <button
                          className="btn btn-sm"
                          onClick={() => setInviting(row)}
                        >
                          Invite
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>

        {!loading && rows.length === 0 && (
          <div className="empty">No customers yet.</div>
        )}
      </div>
    </>
  );
}

function InviteForm({
  customer,
  onIssued,
  onCancel,
  onError,
}: {
  customer: Customer;
  onIssued: (invite: InviteCreated) => void;
  onCancel: () => void;
  onError: (message: string) => void;
}) {
  const [email, setEmail] = useState(customer.email ?? "");
  const [fullName, setFullName] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      onIssued(
        await api.createInvite({
          customer_id: customer.id,
          email,
          full_name: fullName,
        }),
      );
    } catch (err) {
      onError(err instanceof ApiError ? err.message : "Could not create the invite.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="inline-panel" onSubmit={submit}>
      <label>
        Inviting
        <input value={customer.name} readOnly />
      </label>
      <label>
        Their email
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          autoFocus
        />
      </label>
      <label>
        Their name
        <input
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          required
        />
      </label>
      <div className="inline-panel-actions">
        <button className="btn" disabled={busy}>
          {busy ? "Creating…" : "Create invite"}
        </button>
        <button type="button" className="btn btn-quiet" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

/**
 * The link, shown once.
 *
 * Only its hash is stored, so this panel is the single moment the plaintext
 * exists anywhere. That is deliberate -- it means the stored row is not a
 * working invitation -- and it is why this is a panel that has to be dismissed
 * rather than a notification that fades.
 */
function InviteIssued({
  invite,
  onDone,
}: {
  invite: InviteCreated;
  onDone: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const link = `${window.location.origin}${invite.accept_path}`;

  return (
    <div className="notice">
      <div>
        <strong>Invitation ready for {invite.full_name}</strong>
        <div className="subtle" style={{ fontSize: 13 }}>
          Send this link to {invite.email}. It works once, expires{" "}
          {day(invite.expires_at)}, and cannot be shown again.
        </div>
        <code className="invite-link">{link}</code>
      </div>
      <div className="inline-form">
        <button
          className="btn btn-sm"
          onClick={() => {
            void navigator.clipboard.writeText(link);
            setCopied(true);
          }}
        >
          {copied ? "Copied" : "Copy link"}
        </button>
        <button className="btn btn-quiet btn-sm" onClick={onDone}>
          Done
        </button>
      </div>
    </div>
  );
}
