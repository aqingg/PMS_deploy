import { LogLevel } from "@azure/msal-browser";

const appBase = import.meta.env.BASE_URL || "/";
const redirectUri =
  import.meta.env.VITE_AZURE_REDIRECT_URI ||
  window.location.origin + (appBase.endsWith("/") ? appBase : `${appBase}/`);

const clientId = import.meta.env.VITE_AZURE_CLIENT_ID;
const tenantId = import.meta.env.VITE_AZURE_TENANT_ID;

if (!clientId || !tenantId) {
  console.warn(
    "Azure SSO configuration mismatch: VITE_AZURE_CLIENT_ID or VITE_AZURE_TENANT_ID is missing from environmental variables. Please check your .env file."
  );
}

export const msalConfig = {
  auth: {
    clientId,
    authority: `https://login.microsoftonline.com/${tenantId}`,
    redirectUri,
    postLogoutRedirectUri: redirectUri,
  },
  cache: {
    cacheLocation: "localStorage",
    storeAuthStateInCookie: true,
  },
  system: {
    loggerOptions: {
      loggerCallback: (level, message, containsPii) => {
        if (containsPii) {
          return;
        }
        switch (level) {
          case LogLevel.Error:
            console.error(message);
            return;
          case LogLevel.Info:
            console.info(message);
            return;
          case LogLevel.Verbose:
            console.debug(message);
            return;
          case LogLevel.Warning:
            console.warn(message);
            return;
          default:
            return;
        }
      },
    },
  },
};

export const loginRequest = {
  scopes: ["openid", "profile", "email"] 
};

export const graphConfig = {
  graphMeEndpoint: "https://graph.microsoft.com/v1.0/me",
};
