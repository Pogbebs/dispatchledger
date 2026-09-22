import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth";

export default function Layout() {
  const { user, signOut } = useAuth();

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
        </nav>
      </header>

      <main className="page">
        <Outlet />
      </main>
    </>
  );
}
