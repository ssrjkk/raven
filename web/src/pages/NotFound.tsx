import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] space-y-4">
      <h1 className="text-6xl font-bold text-gray-700">404</h1>
      <p className="text-gray-500 text-lg">Page not found</p>
      <Link
        to="/"
        className="bg-violet-600 hover:bg-violet-500 text-white px-5 py-2 rounded-xl text-sm font-medium transition"
      >
        Back to Dashboard
      </Link>
    </div>
  );
}