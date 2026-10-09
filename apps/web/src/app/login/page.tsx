"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { apiFetch, ApiError, type Profile } from "@/lib/api";
import { isSupabaseConfigured } from "@/lib/env";
import { createClient } from "@/lib/supabase/client";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (!isSupabaseConfigured()) {
      setError("Supabase client keys are not configured in apps/web/.env.local");
      return;
    }
    setPending(true);
    try {
      const supabase = createClient();
      const { data, error: signError } = await supabase.auth.signInWithPassword({ email, password });
      if (signError) {
        setError(signError.message);
        return;
      }
      if (!data.session) {
        setError("Supabase did not return an authenticated session.");
        return;
      }
      await apiFetch<Profile>("/api/v1/me", data.session.access_token);
      router.replace("/app");
    } catch (requestError) {
      if (requestError instanceof ApiError) {
        setError(`Your credentials were accepted, but the PharmaIntelligence API could not load your profile: ${requestError.message}`);
      } else {
        setError("Could not reach Supabase or the PharmaIntelligence API. Check that both services are running.");
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <Link href="/" className="mb-8 text-sm text-sage-600">
        ← PharmaIntelligence
      </Link>
      <div className="card">
        <h1 className="text-xl font-semibold">Sign in</h1>
        <p className="mt-1 text-sm text-slate-600">Use the same account for web and, later, Telegram.</p>
        <form className="mt-6 space-y-4" onSubmit={onSubmit}>
          <label className="block text-sm">
            Email
            <input className="input mt-1" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label className="block text-sm">
            Password
            <input
              className="input mt-1"
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          {error ? <p className="text-sm text-red-700">{error}</p> : null}
          <button className="btn-primary w-full" disabled={pending} type="submit">
            {pending ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="mt-4 text-sm text-slate-600">
          No account?{" "}
          <Link className="text-sage-600" href="/register">
            Register
          </Link>
        </p>
      </div>
    </main>
  );
}
