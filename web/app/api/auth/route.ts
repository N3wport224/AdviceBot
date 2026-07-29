import { gateEnabled, passwordOk } from "@/lib/auth-server";

export const runtime = "nodejs";

/** GET /api/auth → { required: boolean } — lets the client skip the lock
 * screen entirely on deployments with no ACCESS_PASSWORD configured. */
export async function GET() {
  return Response.json({ required: gateEnabled() });
}

/** POST /api/auth { password } → 204 on success, 401 on wrong password. */
export async function POST(req: Request) {
  let password = "";
  try {
    ({ password = "" } = await req.json());
  } catch {
    /* empty body → empty password */
  }
  if (!passwordOk(password)) {
    return new Response("Wrong password", { status: 401 });
  }
  return new Response(null, { status: 204 });
}
