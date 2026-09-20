"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError, ApiUnreachableError, signup } from "../../lib/api";
import { useAuth } from "../../lib/auth";

export default function SignupPage() {
  const router = useRouter();
  const { refreshUser } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [orgName, setOrgName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await signup(email.trim(), password, orgName.trim());
      await refreshUser();
      router.push("/app");
    } catch (err) {
      if (err instanceof ApiUnreachableError || err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Something went wrong. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen bg-slate-50">
      <div className="mx-auto flex w-full max-w-md flex-col justify-center px-6 py-12">
        <Link href="/" className="mb-8 flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-sm font-bold text-white">$</span>
          <span className="text-lg font-semibold tracking-tight text-slate-900">AI Cost Doctor</span>
        </Link>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Analyze your AI spend</h1>
        <p className="mt-2 text-sm text-slate-600">Create your account to see your customer P&L.</p>

        <form onSubmit={onSubmit} className="mt-8 space-y-5">
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert">
              {error}
            </div>
          )}
          <div>
            <label htmlFor="org" className="block text-sm font-medium text-slate-700">Organization name</label>
            <input
              id="org" type="text" required value={orgName} onChange={(e) => setOrgName(e.target.value)}
              placeholder="Acme AI"
              className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>
          <div>
            <label htmlFor="email" className="block text-sm font-medium text-slate-700">Work email</label>
            <input
              id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com" autoComplete="email"
              className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>
          <div>
            <label htmlFor="password" className="block text-sm font-medium text-slate-700">Password</label>
            <input
              id="password" type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)}
              placeholder="At least 8 characters" autoComplete="new-password"
              className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>
          <button
            type="submit" disabled={submitting}
            className="w-full rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {submitting ? "Creating account…" : "Create account"}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-slate-600">
          Already have an account? <Link href="/login" className="font-semibold text-indigo-600 hover:text-indigo-800">Sign in</Link>
        </p>
        <p className="mt-4 text-center text-sm text-slate-500">
          Just want to look around? <Link href="/demo" className="font-semibold text-indigo-600 hover:text-indigo-800">See the demo</Link> — no signup, no API key.
        </p>
      </div>
    </div>
  );
}
