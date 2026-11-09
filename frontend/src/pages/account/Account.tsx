import { avatarUrl } from "../../api";
import { useAuth } from "../../auth";
import { useDocumentTitle } from "../../ui";

import ProfileSection from "./components/ProfileSection";
import EmailSection from "./components/EmailSection";
import PasswordSection from "./components/PasswordSection";
import DeleteSection from "./components/DeleteSection";

export default function Account() {
  useDocumentTitle("Account");

  const { user } = useAuth();

  return (
    <div className="shell page">
      <div className="identity">
        {user && (
          <img
            src={avatarUrl(user.email_hash, 80)}
            alt=""
            width={64}
            height={64}
          />
        )}

        <div>
          <h1>Account</h1>
          <p className="lede">{user?.email}</p>
        </div>
      </div>

      <div className="sections">
        <ProfileSection />
        <EmailSection />
        <PasswordSection />
        <DeleteSection />
      </div>
    </div>
  );
}