import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth";

export default function Layout() {
  const { user, signOut, reconnecting } = useAuth();

  return (
    <>
      <header className="header">
        <div className="header-top">
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <div className="brand">
              DispatchLedger
            </div>
            {/* Always visible, because "which company am I looking at" is the
                whole point of the demo. */}
            <span className="tenant-badge">
              <span className="dot" />
              {user?.tenant_name}
            </span>
          </div>

          <div className="header-right">
            <span>
              {user?.full_name} &middot; {user?.role}
            </span>
            <button className="btn btn-quiet btn-sm" onClick={signOut}>
              Sign out
            </button>
          </div>
        </div>

        <nav className="nav">
          <NavLink to="/orders">Orders</NavLink>
          <NavLink to="/deliveries">Deliveries</NavLink>
          <NavLink to="/customers">Customers</NavLink>
          <NavLink to="/invoices">Invoices</NavLink>
          <NavLink to="/insights">Insights</NavLink>
        </nav>
      </header>

      {reconnecting && (
        <div className="reconnecting" role="status">
          Reconnecting to the server — your session is still valid.
        </div>
      )}

      <main className="page">
        <Outlet />
      </main>
    </>
  );
}
