import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth";

/**
 * The customer's shell.
 *
 * Deliberately not the staff layout with items hidden. A customer is not a
 * member of staff with fewer permissions -- they are looking at a different
 * application that happens to share a database. The badge names their own
 * company, with the distributor's name beside it as context rather than as
 * the thing in view.
 */
export default function PortalLayout() {
  const { user, signOut } = useAuth();

  return (
    <>
      <header className="header">
        <div className="header-top">
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <div className="brand">DispatchLedger</div>
            <span className="tenant-badge">
              <span className="dot" />
              {user?.customer_name}
            </span>
            <span className="subtle" style={{ fontSize: 13 }}>
              supplied by {user?.tenant_name}
            </span>
          </div>

          <div className="header-right">
            <span>{user?.full_name}</span>
            <button className="btn btn-quiet btn-sm" onClick={signOut}>
              Sign out
            </button>
          </div>
        </div>

        <nav className="nav">
          <NavLink to="/portal/orders">My orders</NavLink>
          <NavLink to="/portal/invoices">Invoices</NavLink>
        </nav>
      </header>

      <main className="page">
        <Outlet />
      </main>
    </>
  );
}
