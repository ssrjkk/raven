import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] space-y-4 text-center">
      <h1 className="text-7xl font-black tracking-tight gradient-text">404</h1>
      <p className="text-lg text-tertiary">Page not found</p>
      <p className="text-sm text-tertiary max-w-sm">
        The page you're looking for doesn't exist or has been moved.
      </p>
      <Link to="/" className="btn-primary">
        Back to Dashboard
      </Link>
    </div>
  );
}
