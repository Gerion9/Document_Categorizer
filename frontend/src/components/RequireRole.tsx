import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";

interface RequireRoleProps {
  role?: string;
  roles?: string[];
  redirectTo?: string;
}

export function RequireRole({ role, roles, redirectTo = "/" }: RequireRoleProps) {
  const { user, loading } = useAuth();

  if (loading) {
    return null;
  }

  if (!user) {
    return <Navigate to={redirectTo} replace />;
  }

  const acceptedRoles = (roles && roles.length > 0 ? roles : role ? [role] : [])
    .map((value) => value.toLowerCase());
  const hasRole = user.roles?.some((r) => acceptedRoles.includes(r.toLowerCase()));

  if (!hasRole) {
    return <Navigate to={redirectTo} replace />;
  }

  return <Outlet />;
}
