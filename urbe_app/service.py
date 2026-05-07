from ._loader import export_public, load_root_module

module = load_root_module("urbe_app._legacy_service", "service.py")
export_public(module, globals())


def normalize_pix_key(value):
    return str(value or "").strip()


def sanitize_user(user):
    public = module.sanitize_user(user)
    pix_key = normalize_pix_key(user.get("pixKey"))
    if pix_key:
        public["pixKey"] = pix_key
        public["pixKeyType"] = str(user.get("pixKeyType") or "").strip() or None
    return public


module.sanitize_user = sanitize_user


class UrbeService(module.UrbeService):
    def register_user(self, payload):
        normalized_email = module.normalize_email(payload.get("email"))
        normalized_name = str(payload.get("name") or "").strip()
        pix_key = normalize_pix_key(payload.get("pixKey"))
        pix_key_type = str(payload.get("pixKeyType") or "").strip().lower()

        if not normalized_name:
            raise module.AppError("Nome e obrigatorio.", 400, "VALIDATION_ERROR")
        if not normalized_email or "@" not in normalized_email:
            raise module.AppError("E-mail invalido.", 400, "VALIDATION_ERROR")
        if pix_key_type and pix_key_type not in {"cpf", "cnpj", "email", "phone", "random"}:
            raise module.AppError("Tipo de chave Pix invalido.", 400, "VALIDATION_ERROR")

        def tx(db):
            self._cleanup_expired_reservations(db)
            existing = next((user for user in db["users"] if user["email"] == normalized_email), None)
            if existing:
                raise module.AppError("Ja existe usuario com este e-mail.", 409, "EMAIL_IN_USE")

            now = module.now_iso()
            user = {
                "id": module.next_id(db, "user", "usr"),
                "name": normalized_name,
                "email": normalized_email,
                "role": "member",
                "passwordHash": module.hash_password(payload.get("password")),
                "pixKey": pix_key or None,
                "pixKeyType": pix_key_type or None,
                "createdAt": now,
            }
            db["users"].append(user)

            session = self._create_session(db, user["id"], now)
            return {
                "user": sanitize_user(user),
                "sessionToken": session["token"],
                "expiresAt": session["expiresAt"],
            }

        return self.store.transaction(tx)

    def _create_payment_order(self, db, data):
        enriched = module.clone(data)
        seller = next((user for user in db["users"] if user["id"] == enriched.get("sellerId")), None)
        seller_pix_key = normalize_pix_key((seller or {}).get("pixKey"))
        seller_pix_key_type = str((seller or {}).get("pixKeyType") or "").strip().lower()
        if seller_pix_key:
            enriched["sellerPixKey"] = seller_pix_key
            enriched["sellerPixKeyType"] = seller_pix_key_type or None
        return super()._create_payment_order(db, enriched)


# Re-export patched symbols.
globals()["UrbeService"] = UrbeService
globals()["sanitize_user"] = sanitize_user
