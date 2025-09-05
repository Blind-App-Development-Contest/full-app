// supabase/functions/issue-jwt/index.ts
import { serve } from "https://deno.land/std@0.168.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import { sign } from "https://deno.land/x/djwt@v2.8/mod.ts";

// Supabase JWT Secret은 환경 변수로 접근 가능
const SUPABASE_JWT_SECRET = Deno.env.get("SUPABASE_JWT_SECRET");
const SUPABASE_URL = Deno.env.get("SUPABASE_URL");
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY"); // DB 접근용

serve(async (req) => {
  if (req.method !== "POST") {
    return new Response(JSON.stringify({ error: "Method Not Allowed" }), {
      status: 405,
      headers: { "Content-Type": "application/json" },
    });
  }

  try {
    const { device_uuid } = await req.json();

    if (!device_uuid) {
      return new Response(JSON.stringify({ error: "device_uuid is required" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }

    // 1. Supabase DB에서 device_uuid 유효성 검사 (service_role_key 사용)
    //    'users' 테이블의 'user_id' 컬럼에 해당 device_uuid가 존재하는지 확인
    const supabaseAdmin = createClient(
      SUPABASE_URL!,
      SUPABASE_SERVICE_ROLE_KEY!,
      {
        auth: {
          persistSession: false,
        },
      }
    );

    const { data: user, error: dbError } = await supabaseAdmin
      .from("users") // 'users' 테이블에서 device_uuid를 user_id로 사용한다고 가정
      .select("user_id")
      .eq("user_id", device_uuid)
      .single();

    if (dbError || !user) {
      console.error("DB Error or user not found:", dbError?.message || "User not found");
      return new Response(JSON.stringify({ error: "Invalid device UUID" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      });
    }

    // 2. JWT 페이로드 생성
    const payload = {
      device_uuid: device_uuid,
      exp: Math.floor(Date.now() / 1000) + (60 * 60 * 24), // 24시간 후 만료
      sub: device_uuid,
      role: "authenticated",
    };

    // 3. JWT 서명 및 발행
    const jwt = await sign(payload, SUPABASE_JWT_SECRET!);

    return new Response(JSON.stringify({ access_token: jwt, token_type: "bearer" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  } catch (error) {
    console.error("Function error:", error.message);
    return new Response(JSON.stringify({ error: "Internal Server Error" }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }
});
