// ---------------------------------------------------------
// AppContext.js —— 前端 B（完整修复版 + Transfer Data）
// Copy Template 最小方案：新增 copyApplicationTemplate()
// Public Link 初始化改为 createFolders，只创建 A.Vehicle_integration 下 01-07
// Transfer Data：新增单 Project Download / Import
// ---------------------------------------------------------

import React, {
  createContext,
  useState,
  useEffect,
  useCallback,
  useContext,
  useRef,
} from "react";
import axios from "axios";
import { message } from "antd";

export const AppContext = createContext(null);
export const useAppContext = () => useContext(AppContext);

export function AppProvider({ children }) {
  // =====================================================
  // 0. API 管理（全局统一）
  // =====================================================
  const API = {
    LOCAL: "http://127.0.0.1:7175",
    LOCAL_CREATE_FOLDERS: "/createFolders",
    LOCAL_COPY_APPLICATION_TEMPLATE: "/copyApplicationTemplate",
    LOCAL_RENAME_CALIBRATION_FOLDER: "/renameCalibrationFolder",

    // 调试时建议用本地： http://127.0.0.1:8086/app-puma
    BASE: "https://oss-dthub.apac.bosch.com/app-puma",
    //BASE: "http://127.0.0.1:8086/app-puma",

    PROJECT_GET: "/project/getProject",
    PROJECT_CREATE: "/project/createProject",
    PROJECT_CREATE_CALIBRATION_WORKSPACE: "/project/createCalibrationWorkspace",
    PROJECT_INFO_UPDATE: "/project/updateProjectInfo",
    PROJECT_WF_UPDATE: "/project/updateWorkFlow",
    PROJECT_GETPATH: "/project/getPath",

    // Transfer Data
    PROJECT_DATA_DOWNLOAD: "/project/downloadProject",
    PROJECT_DATA_IMPORT: "/project/importProject",

    // Parameter
    PROJECT_GETUUID: "/project/getProjectUUID",
    TEMPLATE_TASK_DETAIL: "/template/getTaskDetail",
    TEMPLATE_TEAM: "/template/teamMembers",
    TEMPLATE_WF: "/project/getWorkFlowTemplate",
    SSE: "/sse/stream",
    PMS: "http://127.0.0.1:8000/api/v1/projects/info",
  };

  const SimpleProjectInfoList =
    "https://apiroutecccn.apac.bosch.com/openapi/pmsserverprod/api/getSimpleProjectInfoList";
  const gatewayKey = "PN9rSrBi6770yG35WSoN25yAPiWaqbBS";

  const request = useCallback(
    (method, url, { params = {}, data = {} } = {}) =>
      axios({ method, url, params, data }),
    []
  );

  // =====================================================
  // ⭐ 全局状态
  // =====================================================
  const [msgQueue, setMsgQueue] = useState([]);
  const [user, setUser] = useState({ username: "Unknown", department: "Unknown" });
  const [projectName, setProjectName] = useState(null);
  const [projectId, setProjectId] = useState(null);
  const [projectInfo, setProjectInfo] = useState(null);
  const [projectWorkFlow, setProjectWorkFlow] = useState(null);
  const [projectProgress, setProjectProgress] = useState(0);
  const [messageApi, contextHolder] = message.useMessage();
  const [loading, setLoading] = useState(false);
  const [needCreate, setNeedCreate] = useState(false);
  const [selectableDepartments, setSelectableDepartments] = useState([]);
  const [selectedDepartment, setSelectedDepartment] = useState(null);
  const [, setEventSource] = useState(null);
  const [refreshFlag, setRefreshFlag] = useState(0);
  const projectIdRef = useRef(null);
  const [teamMembers, setTeamMembers] = useState([]);

  // =====================================================
  // ⭐ 解析 URL + localStorage
  // =====================================================
  const resolveProjectId = () => {
    const search = window.location.search || "";
    const hash = window.location.hash || "";

    if (search.includes("projectId=")) {
      return Number(new URLSearchParams(search).get("projectId"));
    }

    if (hash.includes("projectId=")) {
      return Number(new URLSearchParams(hash.split("?")[1]).get("projectId"));
    }

    const parts = hash.replace("#/", "").split("/");
    if (parts[0] === "task" && parts[1]) {
      return Number(parts[1]);
    }

    return Number(localStorage.getItem("projectId"));
  };

  // =====================================================
  // ⭐ initApp
  // =====================================================
  const initApp = useCallback(async () => {
    try {
      setLoading(true);

      const pid = resolveProjectId();
      if (pid) localStorage.setItem("projectId", pid);
      setProjectId(pid ?? null);

      const userinfo = await request("GET", API.LOCAL + "/userinfo");
      const username = userinfo.data?.machine_id;
      if (!username) return;

      let tmpUser = { username, department: "Unknown" };
      let info = null;
      let wf = null;
      let rate = 0;
      let pname = null;

      if (pid) {
        const res = await request("GET", API.BASE + API.PROJECT_GET, {
          params: { username, projectId: pid },
        });

        if (res.data.exists === false) {
          setNeedCreate(true);
          setSelectableDepartments(
            Array.isArray(res.data.departments) ? res.data.departments : []
          );
          setUser(tmpUser);
          return;
        }

        const data = res.data.data;
        tmpUser.department = data.department;
        info = structuredClone(data.projectInfo);
        wf = data.projectWorkFlow;
        pname = data.projectName;
        rate = data.projectInfoRate ?? 0;
      }

      setUser(tmpUser);
      setProjectInfo(info);
      setProjectWorkFlow(wf);
      setProjectProgress(rate);
      setProjectName(pname);
    } catch (err) {
      console.error("initApp failed:", err);
    } finally {
      setLoading(false);
    }
  }, [request, API.BASE, API.LOCAL, API.PROJECT_GET]);

  useEffect(() => {
    initApp();
  }, [initApp]);

  useEffect(() => {
    if (projectId) {
      projectIdRef.current = projectId;
      localStorage.setItem("projectId", projectId);
    }
  }, [projectId]);

  // =====================================================
  // ⭐ SSE 连接
  // =====================================================
  const connectSSE = useCallback(() => {
    if (!user.username || user.username === "Unknown") return;

    const url = API.BASE + API.SSE + `?user=${user.username}`;
    console.log(" Connecting SSE:", url);
    const es = new EventSource(url);
    es.onopen = () => console.log(" SSE Connected");

    es.onmessage = (ev) => {
      if (!ev.data) return;

      let msg = null;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }

      const { event, payload } = msg;
      const currentPid = projectIdRef.current;

      if (event === "ProjectUpdated" && payload.projectId === currentPid) {
        setMsgQueue((q) => [...q, { evt: "ProjectUpdated", payload }]);
        setRefreshFlag((v) => v + 1);
        return;
      }

      if (event === "WorkflowUpdated" && payload.projectId === currentPid) {
        setMsgQueue((q) => [...q, { evt: "WorkflowUpdated", payload }]);
        setRefreshFlag((v) => v + 1);
        return;
      }

      if (event === "ProjectDeleted" && payload.projectId === currentPid) {
        messageApi.error("❌ 当前项目已被删除");
        localStorage.removeItem("projectId");
        window.location.hash = "#/edit";
      }
    };

    es.onerror = () => {
      console.log(" SSE disconnected, reconnecting...");
      es.close();
      setTimeout(connectSSE, 2000);
    };

    setEventSource(es);
  }, [user.username, API.BASE, API.SSE, messageApi]);

  useEffect(() => {
    connectSSE();
  }, [connectSSE]);

  useEffect(() => {
    if (projectId !== null && user.username !== "Unknown") {
      initApp();
    }
  }, [refreshFlag, initApp, projectId, user.username]);

  // =====================================================
  // ⭐ 文件夹功能 —— requestPathAndExecute
  // =====================================================
  const getRealPathFromBackend = async ({ label, taskId, projectId, user, type }) => {
    const params = {
      label,
      taskId,
      projectId,
      username: user.username,
      department: user.department,
    };

    if (type) {
      params.type = type;
    }

    const res = await axios.get(API.BASE + API.PROJECT_GETPATH, {
      params,
    });

    if (!res.data?.success) {
      console.error("❌ getPath failed", res.data);
      messageApi.error("路径解析失败");
    }

    const realPath = res.data.path;
    if (!realPath) {
      messageApi.error("后端未返回有效路径");
    }

    console.log(" Path from backend:", realPath);
    return realPath;
  };

  const getOfficeFiles = async (folderPath) => {
    if (!folderPath || typeof folderPath !== "string") {
      console.error("提供的文件夹路径无效。");
      messageApi.error("提供的文件夹路径无效。");
      return [];
    }

    try {
      const url = `${API.LOCAL}/getOfficeFiles`;
      const response = await axios.get(url, { params: { folder_path: folderPath } });
      return response.data;
    } catch (error) {
      if (error.response) {
        console.error(
          `获取文件列表失败: ${error.response.status} - ${
            error.response.data.detail || error.response.statusText
          }`
        );
        messageApi.error("获取文件列表失败");
      } else {
        console.error("网络或请求错误:", error.message);
        messageApi.error("网络或请求错误");
      }
      return [];
    }
  };

  const requestPathAndExecute = async ({ label, taskId, mode, type }) => {
    if (!projectId || !user?.username) {
      console.warn("❗ 缺少 projectId 或 user，无法打开路径");
      return;
    }

    try {
      const realPath = await getRealPathFromBackend({
        label,
        taskId,
        projectId,
        user,
        type,
      });

      const clientEndpoint =
        mode === "open" ? API.LOCAL + "/openPath" : API.LOCAL + "/copyPath";

      await axios.get(clientEndpoint, { params: { path: realPath } });

      if (mode === "open") {
        messageApi.success(`已打开 ${type} 文件夹`);
      } else {
        messageApi.success(`已复制 ${type} 路径到剪贴板`);
      }

      console.log(`✨ ${mode === "open" ? "open" : "copy"} success →`, realPath);
    } catch (err) {
      console.error("❌ requestPathAndExecute error:", err);
      messageApi.error("本地客户端操作失败");
    }
  };

  const actions = {
    openLocal: (payload) => requestPathAndExecute({ ...payload, mode: "open", type: "local" }),
    copyLocal: (payload) => requestPathAndExecute({ ...payload, mode: "copy", type: "local" }),
    openPublic: (payload) =>
      requestPathAndExecute({ ...payload, mode: "open", type: "public" }),
    copyPublic: (payload) =>
      requestPathAndExecute({ ...payload, mode: "copy", type: "public" }),
    openCloud: (payload) => requestPathAndExecute({ ...payload, mode: "open", type: "cloud" }),
    copyCloud: (payload) => requestPathAndExecute({ ...payload, mode: "copy", type: "cloud" }),
  };

  // =====================================================
  // ⭐ API 操作（保持原逻辑）
  // =====================================================
  const createProject = async () => {
    try {
      const name = window.prompt("请输入项目名");
      await request("POST", API.BASE + API.PROJECT_CREATE, {
        data: {
          username: user.username,
          projectName: name,
          department: selectedDepartment,
          owner: user.username,
          editors: [user.username],
        },
      });
      setNeedCreate(false);
      setSelectedDepartment(null);
      initApp();
    } catch (err) {
      console.error("createProject failed:", err);
    }
  };

  const rewriteProjectInfo = async (finalData) => {
    try {
      const res = await request("POST", API.BASE + API.PROJECT_INFO_UPDATE, {
        data: finalData,
      });
      setProjectInfo(structuredClone(res.data.data.projectInfo));
      setProjectProgress(res.data.data.projectInfoRate ?? 0);
      return { success: true };
    } catch (err) {
      return { success: false };
    }
  };

  const updateWorkFlow = async (finalData) => {
    try {
      const res = await request("POST", API.BASE + API.PROJECT_WF_UPDATE, {
        data: finalData,
      });
      setProjectWorkFlow(res.data.data.projectWorkFlow);
      return { success: true };
    } catch (err) {
      return { success: false };
    }
  };

  // =====================================================
  // Transfer Data
  // =====================================================
  const parseDownloadFileName = (contentDisposition, fallbackName) => {
    if (!contentDisposition) return fallbackName;

    const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
    if (utf8Match?.[1]) {
      try {
        return decodeURIComponent(utf8Match[1].trim());
      } catch {
        return utf8Match[1].trim();
      }
    }

    const normalMatch = contentDisposition.match(/filename="?([^";]+)"?/i);
    return normalMatch?.[1]?.trim() || fallbackName;
  };

  const readBlobErrorDetail = async (err, fallback) => {
    try {
      const blob = err?.response?.data;
      if (blob instanceof Blob) {
        const text = await blob.text();
        const parsed = JSON.parse(text);
        return parsed?.detail || parsed?.message || fallback;
      }
    } catch {
      // ignore secondary parsing errors
    }

    return (
      err?.response?.data?.detail ||
      err?.response?.data?.message ||
      err?.message ||
      fallback
    );
  };

  const downloadProjectData = async (targetProjectId = projectId) => {
    if (!targetProjectId) {
      return { success: false, message: "projectId is missing" };
    }

    if (!user?.username || user.username === "Unknown") {
      return { success: false, message: "username is missing" };
    }

    try {
      const res = await axios.get(API.BASE + API.PROJECT_DATA_DOWNLOAD, {
        params: {
          username: user.username,
          projectId: targetProjectId,
        },
        responseType: "blob",
      });

      const fallbackName = `${projectName || "Project"}.puma.json`;
      const fileName = parseDownloadFileName(
        res.headers?.["content-disposition"],
        fallbackName
      );

      return {
        success: true,
        blob: res.data,
        fileName,
      };
    } catch (err) {
      console.error("downloadProjectData failed:", err);
      const detail = await readBlobErrorDetail(
        err,
        "Download Project Data request failed"
      );
      return { success: false, message: detail };
    }
  };

  const importProjectData = async (projectData) => {
    if (!projectData || typeof projectData !== "object") {
      return { success: false, message: "Project data is empty or invalid" };
    }

    if (!user?.username || user.username === "Unknown") {
      return { success: false, message: "username is missing" };
    }

    try {
      const res = await request("POST", API.BASE + API.PROJECT_DATA_IMPORT, {
        data: {
          username: user.username,
          projectData,
        },
      });

      if (!res.data?.success || !res.data?.data?.id) {
        return {
          success: false,
          message: res.data?.message || "Import Project Data failed",
        };
      }

      return {
        success: true,
        projectId: res.data.data.id,
        projectName: res.data.data.projectName,
        data: res.data.data,
      };
    } catch (err) {
      console.error("importProjectData failed:", err);
      const detail =
        err.response?.data?.detail ||
        err.response?.data?.message ||
        err.message ||
        "Import Project Data request failed";
      return { success: false, message: detail };
    }
  };

  const getTaskDetail = async (taskName) => {
    try {
      const res = await request("GET", API.BASE + API.TEMPLATE_TASK_DETAIL, {
        params: { taskName },
      });
      return { success: true, data: res.data };
    } catch {
      return { success: false };
    }
  };

  const getWorkFlowTemplate = async () => {
    try {
      const res = await request("GET", API.BASE + API.TEMPLATE_WF);
      if (res.data?.success) return { success: true, data: res.data.data };
      return { success: false };
    } catch {
      return { success: false };
    }
  };

  const loadTeamMembers = async () => {
    try {
      const res = await request("GET", API.BASE + API.TEMPLATE_TEAM);
      setTeamMembers(res.data.members || []);
      return res.data.members;
    } catch {
      return [];
    }
  };

  const getProjectFromPMS = async () => {
    try {
      const url = `${SimpleProjectInfoList}?gatewayKey=${gatewayKey}`;
      const res = await request("Get", url);
      const validProjects = res.data.data
        .filter((item) => item.product_category?.startsWith("AB1"))
        .filter((item) => item.status !== "Canceled");
      return validProjects;
    } catch (error) {
      console.error("Failed to execute getProjectFromPMS:", error);
      return [];
    }
  };

  const getProjectInfoFromPMS = async (uuid) => {
    try {
      const url = `${API.LOCAL}/PMSInfo/${uuid}`;
      const res = await request("Get", url);
      console.log(res.data);
      return res;
    } catch (error) {
      return {};
    }
  };

  const getProjectUUID = async (pid) => {
    const targetProjectId = pid || projectId;
    if (!targetProjectId) {
      console.error("getProjectUUID: Project ID is missing.");
      messageApi.error("缺少项目ID，无法获取UUID");
      return { success: false };
    }

    try {
      const url = `${API.BASE}${API.PROJECT_GETUUID}/${targetProjectId}`;
      const res = await request("GET", url);
      if (res.data.uuid) {
        return { success: true, uuid: res.data.uuid };
      }

      messageApi.error(res.data?.message || "获取项目 UUID 失败");
      return { success: false, message: res.data?.message };
    } catch (err) {
      console.error("getProjectUUID request failed:", err);
      messageApi.error("请求项目 UUID 时出错");
      return { success: false };
    }
  };

  const getParameter = async (parametername) => {
    switch (parametername) {
      case "uuid": {
        const result = await getProjectUUID();
        if (result && result.uuid) {
          return { success: true, parameter: result.uuid };
        }

        const errorMessage = "获取 UUID 失败";
        console.warn(errorMessage);
        messageApi.error(errorMessage);
        return { success: false, parameter: "", message: errorMessage };
      }

      case "projectid": {
        const storedProjectId = localStorage.getItem("projectId");
        if (storedProjectId) {
          return { success: true, parameter: storedProjectId };
        }

        const errorMessage = `在 Local Storage 中未找到 'projectid'`;
        console.warn(errorMessage);
        messageApi.error(errorMessage);
        return { success: false, parameter: "", message: errorMessage };
      }

      default: {
        const errorMessage = `getParameter: 不支持的参数名 "${parametername}"`;
        console.warn(errorMessage);
        messageApi.error(errorMessage);
        return { success: false, parameter: "", message: errorMessage };
      }
    }
  };

  // Public Link 初始化：只创建 A.Vehicle_integration 下的固定目录。
  const SetUpApplicationFloder = async (publicLinkValue) => {
    const publicRoot = String(publicLinkValue || "")
      .trim()
      .replace(/[\\/]+$/, "");
    if (!publicRoot) {
      console.warn("SetUpApplicationFloder: publicLinkValue is empty");
      messageApi.error("Public Link is empty. Cannot create public folders.");
      return 400;
    }

    const joinWinPath = (...parts) =>
      parts
        .map((part, index) => {
          const text = String(part || "").trim();
          if (index === 0) {
            return text.replace(/[\\/]+$/, "");
          }
          return text.replace(/^[\\/]+|[\\/]+$/g, "");
        })
        .filter(Boolean)
        .join("\\");

    const vehicleIntegrationRoot = joinWinPath(
      publicRoot,
      "40.Application",
      "A.Vehicle_integration"
    );

    const vehicleIntegrationSubfolders = [
      "01_Packaging",
      "02_Crash_matrix",
      "03_Sensor_map",
      "04_Mounting_checklist",
      "05_Modal_analysis",
      "06_TCU_No_9_Sens_dir",
      "07_Special_studies",
    ];

    const folders = [
      vehicleIntegrationRoot,
      ...vehicleIntegrationSubfolders.map((folderName) =>
        joinWinPath(vehicleIntegrationRoot, folderName)
      ),
    ];

    try {
      const res = await request("POST", API.LOCAL + API.LOCAL_CREATE_FOLDERS, {
        data: { folders },
      });

      console.log("Public Link A.Vehicle_integration folders created:", folders);
      return res.status;
    } catch (err) {
      console.error("SetUpApplicationFloder createFolders failed:", err);
      const detail =
        err.response?.data?.detail ||
        err.response?.data?.message ||
        err.message ||
        "Public Link folder creation failed";
      messageApi.error(detail);
      return err.response?.status || 500;
    }
  };

  const createCalibrationWorkspace = async (calibrationId) => {
    if (!projectId) {
      console.warn("createCalibrationWorkspace: projectId is missing");
      return { success: false, message: "projectId is missing" };
    }
    if (!user?.username || user.username === "Unknown") {
      console.warn("createCalibrationWorkspace: username is missing");
      return { success: false, message: "username is missing" };
    }

    if (!calibrationId || String(calibrationId).trim() === "") {
      console.warn("createCalibrationWorkspace: calibrationId is missing");
      return { success: false, message: "calibrationId is missing" };
    }

    try {
      const res = await request("POST", API.BASE + API.PROJECT_CREATE_CALIBRATION_WORKSPACE, {
        data: {
          projectId,
          username: user.username,
          department: user.department,
          calibrationId: String(calibrationId).trim(),
        },
      });

      if (res.data?.success) {
        console.log("Calibration workspace paths resolved:", res.data.paths);
        return {
          success: true,
          paths: res.data?.paths || {},
          data: res.data,
        };
      }

      return {
        success: false,
        message: res.data?.message || "createCalibrationWorkspace failed",
        data: res.data,
      };
    } catch (err) {
      console.error("createCalibrationWorkspace failed:", err);
      const detail =
        err.response?.data?.detail ||
        err.response?.data?.message ||
        err.message ||
        "createCalibrationWorkspace request failed";
      return { success: false, message: detail };
    }
  };

  const createLocalFolders = async (folders) => {
    const folderList = Array.isArray(folders)
      ? folders.map((folder) => String(folder || "").trim()).filter(Boolean)
      : [];

    if (folderList.length === 0) {
      return { success: false, message: "folders is empty" };
    }

    try {
      const res = await request("POST", API.LOCAL + API.LOCAL_CREATE_FOLDERS, {
        data: { folders: folderList },
      });
      if (res.data?.success) {
        return {
          success: true,
          folders: res.data?.folders || folderList,
          data: res.data,
        };
      }

      return {
        success: false,
        message: res.data?.message || "createLocalFolders failed",
        data: res.data,
      };
    } catch (err) {
      console.error("createLocalFolders failed:", err);
      const detail =
        err.response?.data?.detail ||
        err.response?.data?.message ||
        err.message ||
        "createLocalFolders request failed";
      return { success: false, message: detail };
    }
  };

  const copyApplicationTemplate = async (destinationApplicationDir, calibrationIds = []) => {
    const target = String(destinationApplicationDir || "").trim();
    const normalizedCalibrationIds = Array.isArray(calibrationIds)
      ? calibrationIds.map((id) => String(id || "").trim()).filter(Boolean)
      : [];

    if (!target) {
      return {
        success: false,
        message: "destinationApplicationDir is empty",
      };
    }

    try {
      const res = await request("POST", API.LOCAL + API.LOCAL_COPY_APPLICATION_TEMPLATE, {
        data: {
          destination_application_dir: target,
          calibration_ids: normalizedCalibrationIds,
        },
      });

      if (res.data?.success) {
        return {
          success: true,
          destination_application_dir: res.data?.destination_application_dir || target,
          calibration_ids: res.data?.calibration_ids || normalizedCalibrationIds,
          created_count: res.data?.created_count ?? 0,
          existing_count: res.data?.existing_count ?? 0,
          skipped_count: res.data?.skipped_count ?? res.data?.existing_count ?? 0,
          copied_files_count: res.data?.copied_files_count ?? 0,
          skipped_existing_files_count: res.data?.skipped_existing_files_count ?? 0,
          data: res.data,
        };
      }

      return {
        success: false,
        message: res.data?.message || "copyApplicationTemplate failed",
        data: res.data,
      };
    } catch (err) {
      console.error("copyApplicationTemplate failed:", err);
      const detail =
        err.response?.data?.detail ||
        err.response?.data?.message ||
        err.message ||
        "copyApplicationTemplate request failed";
      return { success: false, message: detail };
    }
  };

  const renameCalibrationFolder = async (
    destinationApplicationDir,
    oldCalibrationId,
    newCalibrationId
  ) => {
    const target = String(destinationApplicationDir || "").trim();
    const oldId = String(oldCalibrationId || "").trim();
    const newId = String(newCalibrationId || "").trim();

    if (!target) {
      return { success: false, message: "destinationApplicationDir is empty" };
    }
    if (!oldId) {
      return { success: false, message: "oldCalibrationId is empty" };
    }
    if (!newId) {
      return { success: false, message: "newCalibrationId is empty" };
    }

    try {
      const res = await request("POST", API.LOCAL + API.LOCAL_RENAME_CALIBRATION_FOLDER, {
        data: {
          destination_application_dir: target,
          old_calibration_id: oldId,
          new_calibration_id: newId,
        },
      });

      if (res.data?.success) {
        return {
          success: true,
          renamed: Boolean(res.data?.renamed),
          old_path: res.data?.old_path,
          new_path: res.data?.new_path,
          data: res.data,
        };
      }

      return {
        success: false,
        message: res.data?.message || "renameCalibrationFolder failed",
        data: res.data,
      };
    } catch (err) {
      console.error("renameCalibrationFolder failed:", err);
      const detail =
        err.response?.data?.detail ||
        err.response?.data?.message ||
        err.message ||
        "renameCalibrationFolder request failed";
      return { success: false, message: detail };
    }
  };

  useEffect(() => {
    if (msgQueue.length === 0) return undefined;

    const timer = setTimeout(() => {
      const users = Array.from(
        new Set(msgQueue.map((m) => m.payload.username || "未知用户"))
      );
      const projectEvents = msgQueue.filter((m) => m.evt === "ProjectUpdated");
      const wfEvents = msgQueue.filter((m) => m.evt === "WorkflowUpdated");
      const parts = [];

      if (projectEvents.length > 0) {
        parts.push(` 项目更新 x${projectEvents.length}`);
      }
      if (wfEvents.length > 0) {
        parts.push(` 工作流更新 x${wfEvents.length}`);
      }

      const finalMsg = `${parts.join("，")}（${users.join("、")}）`;
      messageApi.info(finalMsg);
      setMsgQueue([]);
    }, 1000);

    return () => clearTimeout(timer);
  }, [msgQueue, messageApi]);

  useEffect(() => {
    if (projectName) {
      document.title = `${projectName}`;
    } else {
      document.title = "UnknownProject";
    }
  }, [projectName]);

  // =====================================================
  // ⭐ Provider
  // =====================================================
  return (
    <>
      {contextHolder}
      <AppContext.Provider
        value={{
          user,
          projectId,
          projectInfo,
          projectWorkFlow,
          projectProgress,
          loading,
          projectName,
          needCreate,
          selectableDepartments,
          selectedDepartment,
          setSelectedDepartment,
          createProject,
          rewriteProjectInfo,
          updateWorkFlow,
          downloadProjectData,
          importProjectData,
          getTaskDetail,
          getWorkFlowTemplate,
          getParameter,
          getRealPathFromBackend,
          getOfficeFiles,
          SetUpApplicationFloder,
          createCalibrationWorkspace,
          createLocalFolders,
          copyApplicationTemplate,
          renameCalibrationFolder,
          teamMembers,
          loadTeamMembers,
          getProjectFromPMS,
          getProjectInfoFromPMS,
          messageApi,
          actions,
        }}
      >
        {children}
      </AppContext.Provider>
    </>
  );
}
