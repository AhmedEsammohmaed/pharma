import { createBrowserClient } from "@supabase/ssr";

import { supabasePublishableKey, supabaseUrl } from "@/lib/env";

export function createClient() {
  return createBrowserClient(supabaseUrl, supabasePublishableKey);
}
