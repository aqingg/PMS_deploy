import React, { useState, useEffect, useCallback } from "react";
import { useParams } from "react-router-dom";
import {
  Button,
  Divider,
  Row,
  Col,
  Card,
  message,
  Input,
  Tooltip,
  Modal,
  Form,
  Spin,
} from "antd";
import WorkFlow from "./WorkFlow";
import { useAppContext } from "../../../context/AppContext";
import {
  PauseCircleOutlined,
  SyncOutlined,
  CheckCircleOutlined,
  MinusCircleOutlined,
  EditOutlined,
} from "@ant-design/icons";

export default function TaskDetailPage() {
  const [messageApi, contextHolder] = message.useMessage();
  const { projectId: routeProjectId, taskId } = useParams();

  const {
    projectId: contextProjectId,
    projectWorkFlow,
    projectName,
    projectInfo,
    getParameter,
    getRealPathFromBackend,
    getOfficeFiles,
    user,
    updateWorkFlow,
    getWorkFlowTemplate,
    createCalibrationWorkspace,
    renameCalibrationFolder,
    renameCalibrationWorkspace,
  } = useAppContext();

  const [currentTask, setCurrentTask] = useState(null);

  // 来自 WorkFlow.json 的模板
  const [template, setTemplate] = useState(null);

  // UI — TaskDetail
  const [taskInputs, setTaskInputs] = useState([]);
  const [taskOutputs, setTaskOutputs] = useState([]);
  const [taskOperation, setTaskOperation] = useState(null);
  const [taskDescription, setTaskDescription] = useState("");
  const [taskNotFound, setTaskNotFound] = useState(false);

  // Modal — Edit Task Name
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [newTaskName, setNewTaskName] = useState("");
  const [savingTaskName, setSavingTaskName] = useState(false);

  // Modal — Operation Loading
  const [operationRunning, setOperationRunning] = useState(false);
  const [operationText, setOperationText] = useState("");

  // Modal — Missing Email
  const [missingEmailModalOpen, setMissingEmailModalOpen] = useState(false);

  // 允许中文，不允许真正危险字符
  const ILLEGAL_REGEX = /[/\\<>{}[\]"'`|]/g;
  const WINDOWS_ILLEGAL_REGEX = /[<>:"/\\|?*]/;

  // TCD08 缺少 email 时固定显示的友好提示
  const MISSING_EMAIL_TIP = "请先放置email";

  const isMissingEmailError = (messageText) => {
    const normalized = String(messageText || "").toLowerCase();

    return (
      normalized.includes("no files found in email folder") ||
      normalized.includes("email folder not found") ||
      normalized.includes("customer_approval_email") ||
      normalized.includes("请先放置email")
    );
  };

  const showMissingEmailModal = () => {
    setMissingEmailModalOpen(true);
  };

  const getEffectiveProjectId = useCallback(() => {
    const fromRoute = routeProjectId ? Number(routeProjectId) : null;
    if (Number.isFinite(fromRoute) && fromRoute > 0) return fromRoute;

    const fromContext = contextProjectId ? Number(contextProjectId) : null;
    if (Number.isFinite(fromContext) && fromContext > 0) return fromContext;

    const stored = localStorage.getItem("projectId");
    const fromStorage = stored ? Number(stored) : null;
    if (Number.isFinite(fromStorage) && fromStorage > 0) return fromStorage;

    return null;
  }, [routeProjectId, contextProjectId]);

  const getNodeName = useCallback((node) => {
    return String(
      node?.taskName || node?.name || node?.title || node?.label || ""
    ).trim();
  }, []);

  const isCalibrationParentName = useCallback((name) => {
    const normalized = String(name || "")
      .trim()
      .toLowerCase()
      .replace(/[\s._-]+/g, "");

    return normalized === "ccalibration" || normalized === "calibration";
  }, []);

  const inferApplicationDirFromCalibrationRoot = useCallback((calibrationRoot) => {
    const value = String(calibrationRoot || "").trim();
    if (!value) return "";

    const match = value.match(/^(.*?[\\/]40\.Application)(?:[\\/]|$)/i);
    if (match?.[1]) return match[1];

    // fallback：calibration_root 通常是 ...\40.Application\C.Calibration\{CalibrationID}
    const parts = value.split(/[\\/]+/).filter(Boolean);
    const idx = parts.findIndex((part) => part.toLowerCase() === "40.application");

    if (idx >= 0) {
      const prefix = value.startsWith("\\\\") ? "\\\\" : "";
      const driveMatch = value.match(/^[A-Za-z]:/);

      if (driveMatch) {
        return parts.slice(0, idx + 1).join("\\");
      }

      return prefix + parts.slice(0, idx + 1).join("\\");
    }

    return "";
  }, []);

  const resolveApplicationDir = useCallback(
    async (calibrationId) => {
      if (!createCalibrationWorkspace) {
        return {
          success: false,
          message: "createCalibrationWorkspace is unavailable",
        };
      }

      const workspaceResult = await createCalibrationWorkspace(calibrationId);

      if (!workspaceResult?.success) {
        return {
          success: false,
          message: workspaceResult?.message || "8086 path calculation failed",
        };
      }

      const paths = workspaceResult?.paths || workspaceResult?.data?.paths || {};
      const calibrationRoot = paths.calibration_root || paths.calibrationRoot || "";
      const applicationDir = inferApplicationDirFromCalibrationRoot(calibrationRoot);

      if (!applicationDir) {
        return {
          success: false,
          message: "Failed to infer 40.Application path from calibration_root",
        };
      }

      return {
        success: true,
        applicationDir,
        paths,
      };
    },
    [createCalibrationWorkspace, inferApplicationDirFromCalibrationRoot]
  );

  // ================================
  // 工具函数：根据 UUID 找任务节点
  // ================================
  const findTaskNodeById = useCallback((nodes, id) => {
    for (const node of nodes || []) {
      if (node.id === id) return node;

      if (node.children?.length) {
        const res = findTaskNodeById(node.children, id);
        if (res) return res;
      }
    }

    return null;
  }, []);

  const findParentNodeById = useCallback((nodes, id, parent = null) => {
    for (const node of nodes || []) {
      if (node.id === id) return parent;

      if (node.children?.length) {
        const result = findParentNodeById(node.children, id, node);
        if (result) return result;
      }
    }

    return null;
  }, []);

  // ================================
  // 1) 加载当前任务
  // ================================
  useEffect(() => {
    if (!projectWorkFlow?.taskTree) return;

    const node = findTaskNodeById(projectWorkFlow.taskTree, taskId);
    setCurrentTask(node || null);
  }, [projectWorkFlow, taskId, findTaskNodeById]);

  // ================================
  // 2) 从 AppContext 加载 WorkFlow 模板
  // ================================
  useEffect(() => {
    const loadTemplate = async () => {
      const res = await getWorkFlowTemplate();

      if (res.success) {
        setTemplate(res.data);
      } else {
        console.error("Failed to load workflow template:", res.error);
      }
    };

    loadTemplate();
  }, [getWorkFlowTemplate]);

  // ================================
  // 3) 根据模板填充 inputs / outputs / operation
  // ================================
  useEffect(() => {
    if (!currentTask) return;
    if (!template) return;

    const detail = template[currentTask.taskName];

    if (!detail) {
      setTaskNotFound(true);
      setTaskDescription("No workflow template defined for this task.");
      setTaskInputs([]);
      setTaskOutputs([]);
      setTaskOperation(null);
      return;
    }

    setTaskNotFound(false);
    setTaskInputs(detail.inputs || []);
    setTaskOutputs(detail.outputs || []);
    setTaskOperation(detail.operation || null);
    setTaskDescription(detail.description || "");
  }, [currentTask, template]);

  // ======================================================
  // 提前拦截 — 如果 currentTask 未加载，直接 Loading
  // ======================================================
  if (!currentTask) {
    return (
      <div>
        {contextHolder}
        <div style={{ padding: 20 }}>Loading Task...</div>
      </div>
    );
  }

  // ================================
  // 更新状态
  // ================================
  const updateStatus = async (newStatus) => {
    const effectiveProjectId = getEffectiveProjectId();

    if (!effectiveProjectId) {
      messageApi.error("缺少项目ID，无法更新状态");
      return;
    }

    const updated = JSON.parse(JSON.stringify(projectWorkFlow));
    const task = findTaskNodeById(updated.taskTree, taskId);

    if (!task) {
      messageApi.error("当前任务节点不存在");
      return;
    }

    task.status = newStatus;

    const res = await updateWorkFlow({
      username: user.username,
      department: user.department,
      workflow: updated,
      projectId: effectiveProjectId,
    });

    if (res?.success) {
      setCurrentTask({ ...task });
      return;
    }

    messageApi.error("Status update failed");
  };

  // ================================
  // 保存任务名
  // ================================
  const updateTaskName = async () => {
    if (savingTaskName) return;

    const rawName = String(newTaskName || "");
    const cleaned = rawName.trim().replace(ILLEGAL_REGEX, "");
    const hasIllegalChars = WINDOWS_ILLEGAL_REGEX.test(rawName);

    if (!cleaned.trim()) {
      messageApi.error("Task name cannot be empty");
      return;
    }

    const effectiveProjectId = getEffectiveProjectId();

    if (!effectiveProjectId) {
      messageApi.error("缺少项目ID，无法保存任务名称");
      return;
    }

    const updated = JSON.parse(JSON.stringify(projectWorkFlow));
    const node = findTaskNodeById(updated.taskTree, taskId);

    if (!node) {
      messageApi.error("当前任务节点不存在");
      return;
    }

    const oldTaskName = getNodeName(node);
    const parentNode = findParentNodeById(updated.taskTree, taskId);
    const parentName = getNodeName(parentNode);
    const isCalibrationChild =
      isCalibrationParentName(parentName) && !isCalibrationParentName(oldTaskName);

    if (isCalibrationChild) {
      if (hasIllegalChars) {
        messageApi.error("CalibrationID 不能包含 Windows 非法字符");
        return;
      }

      const siblingNames = (parentNode.children || [])
        .filter((item) => item.id !== taskId)
        .map((item) => getNodeName(item).toLowerCase())
        .filter(Boolean);

      if (siblingNames.includes(cleaned.toLowerCase())) {
        messageApi.error(`CalibrationID 已存在：${cleaned}`);
        return;
      }

      if (cleaned === oldTaskName) {
        setEditModalOpen(false);
        return;
      }

      const renameCalibration = renameCalibrationFolder || renameCalibrationWorkspace;

      if (!renameCalibration) {
        messageApi.error("本地目录重命名函数不可用");
        return;
      }

      setSavingTaskName(true);

      try {
        const pathResult = await resolveApplicationDir(oldTaskName);

        if (!pathResult.success) {
          messageApi.error(pathResult.message || "无法计算本地目录路径");
          return;
        }

        let localResult = null;

        // 当前 AppContext 标准签名：renameCalibrationFolder(destinationApplicationDir, oldId, newId)
        // 同时兼容旧签名：renameCalibrationWorkspace({ oldCalibrationId, newCalibrationId, destinationApplicationDir })
        if (renameCalibration === renameCalibrationFolder) {
          localResult = await renameCalibration(
            pathResult.applicationDir,
            oldTaskName,
            cleaned
          );
        } else {
          localResult = await renameCalibration({
            destinationApplicationDir: pathResult.applicationDir,
            destination_application_dir: pathResult.applicationDir,
            oldCalibrationId: oldTaskName,
            old_calibration_id: oldTaskName,
            newCalibrationId: cleaned,
            new_calibration_id: cleaned,
          });
        }

        if (!localResult?.success) {
          messageApi.error(localResult?.message || "本地目录重命名失败");
          return;
        }

        node.taskName = cleaned;

        const res = await updateWorkFlow({
          username: user.username,
          department: user.department,
          workflow: updated,
          projectId: effectiveProjectId,
        });

        if (res?.success) {
          setCurrentTask({ ...node });
          setEditModalOpen(false);
          messageApi.success("CalibrationID 已同步重命名");
        } else {
          messageApi.error("本地目录已重命名，但 workflow 保存失败");
        }
      } catch (error) {
        console.error("Rename CalibrationID failed:", error);
        messageApi.error(error?.message || "本地目录重命名失败");
      } finally {
        setSavingTaskName(false);
      }

      return;
    }

    setSavingTaskName(true);

    try {
      node.taskName = cleaned;

      const res = await updateWorkFlow({
        username: user.username,
        department: user.department,
        workflow: updated,
        projectId: effectiveProjectId,
      });

      if (res?.success) {
        setCurrentTask({ ...node });
        setEditModalOpen(false);
      } else {
        messageApi.error("Update failed");
      }
    } catch (error) {
      console.error("Update task name failed:", error);
      messageApi.error(error?.message || "Update failed");
    } finally {
      setSavingTaskName(false);
    }
  };

  // ================================
  // 定义 Operation 行为
  // ================================
  async function handleHttpWithParameter(operation_detail) {
    // 0. 获取需要注入的参数名列表
    const { need_parameter: parameterNames } = operation_detail;

    // 校验输入是否为数组
    if (!Array.isArray(parameterNames)) {
      throw new Error("配置错误：'need_parameter' 必须是一个数组。");
    }

    const effectiveProjectId = getEffectiveProjectId();

    if (!effectiveProjectId) {
      throw new Error("缺少项目ID，无法执行操作");
    }

    // 创建一个Promise数组，每个Promise负责获取一个参数
    const parameterPromises = parameterNames.map((name) => getParameter(name));

    // 并行等待所有参数获取完成
    const parameterResults = await Promise.all(parameterPromises);

    const type = "local";
    const isTCD08Fill = operation_detail.url?.includes("/fillTCD08Report");

    let input_files = [];

    if (!isTCD08Fill) {
      const input_path = await getRealPathFromBackend({
        label: taskInputs[0].label,
        taskId,
        projectId: effectiveProjectId,
        user,
        type,
      });

      input_files = await getOfficeFiles(input_path);
    }

    const output_path = await getRealPathFromBackend({
      label: taskOutputs[0].label,
      taskId,
      projectId: effectiveProjectId,
      user,
      type,
    });

    // 1. 构建最终请求体
    let { url, method, body } = operation_detail;
    const finalBody = JSON.parse(JSON.stringify(body || {}));

    // 将获取到的所有参数写入 finalBody
    parameterNames.forEach((name, index) => {
      const parameterValue = parameterResults[index].parameter;
      finalBody[name] = parameterValue;
    });

    finalBody.template_paths = input_files;
    finalBody.save_path = output_path;

    if (isTCD08Fill) {
      finalBody.project_info = projectInfo;
      finalBody.projectId = effectiveProjectId;
      finalBody.taskId = taskId;
    }

    // 2. 发送请求
    const response = await fetch(url, {
      method: method,
      headers: {
        "Content-Type": "application/json",
      },
      body: finalBody ? JSON.stringify(finalBody) : undefined,
    });

    // 3. 错误处理：7175/FastAPI 通常把错误放在 detail 字段里
    if (!response.ok) {
      let errorMessage = `请求失败: ${response.status} ${response.statusText}`;

      try {
        const errorData = await response.json();
        const detail = errorData?.detail || errorData?.message || errorData?.error;

        if (detail) {
          errorMessage = Array.isArray(detail)
            ? detail.map((item) => item?.msg || JSON.stringify(item)).join("; ")
            : String(detail);
        }
      } catch (e) {
        // 响应体不是 JSON 或为空时，保留默认 HTTP 错误
      }

      const error = new Error(
        isTCD08Fill && isMissingEmailError(errorMessage)
          ? MISSING_EMAIL_TIP
          : errorMessage
      );
      error.status = response.status;
      error.originalMessage = errorMessage;
      error.isMissingEmail = isTCD08Fill && isMissingEmailError(errorMessage);
      throw error;
    }

    // 4. 成功处理：如果业务层返回 success:false，也按失败处理
    try {
      const result = await response.json();

      if (result && result.success === false) {
        const detail = result.detail || result.message || result.error || "操作失败";
        const error = new Error(
          isTCD08Fill && isMissingEmailError(detail) ? MISSING_EMAIL_TIP : String(detail)
        );
        error.originalMessage = String(detail);
        error.isMissingEmail = isTCD08Fill && isMissingEmailError(detail);
        throw error;
      }

      return result;
    } catch (e) {
      if (e?.isMissingEmail) {
        throw e;
      }
      return null; // 响应体为空或不是 JSON
    }
  }

  const executeOperation = () => {
    if (!taskOperation) {
      messageApi.warning("This task requires manual operation.");
      return;
    }

    if (operationRunning) {
      return;
    }

    // 下面的内容需要按照 Operation 的 type 进行处理
    const { operation_name, operation_detail } = taskOperation;
    const { type } = operation_detail;

    setOperationText(`正在执行: ${operation_name}，请稍候...`);
    setOperationRunning(true);

    void (async () => {
      let caughtError = null;

      try {
        switch (type) {
          case "httpWithParameter":
            await handleHttpWithParameter(operation_detail);
            messageApi.success(`${operation_name} 执行完成`);
            break;
          case "httpWithoutParameter":
            break;
          default:
            break;
        }
      } catch (error) {
        caughtError = error;
        console.error("操作失败:", error);
      } finally {
        setOperationRunning(false);
        setOperationText("");
      }

      if (!caughtError) {
        return;
      }

      if (caughtError.isMissingEmail || isMissingEmailError(caughtError.message)) {
        showMissingEmailModal();
        return;
      }

      Modal.error({
        title: "操作失败",
        content: caughtError.message || "操作失败，请查看控制台获取详情。",
        okText: "确定",
      });
    })();
  };

  // ================================
  // UI
  // ================================
  return (
    <div>
      {contextHolder}

      {/* Header */}
      <Row align="middle">
        <Col flex="auto">
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <h1 className="text-2xl font-bold m-0">{currentTask.taskName}</h1>

            <Tooltip title="Edit Task Name">
              <Button
                type="text"
                icon={<EditOutlined />}
                onClick={() => {
                  setNewTaskName(currentTask.taskName);
                  setEditModalOpen(true);
                }}
              />
            </Tooltip>
          </div>

          <p style={{ marginTop: 4, color: "#666", fontSize: 15 }}>
            {taskDescription}
          </p>
        </Col>
      </Row>

      <Divider />

      {/* ===== Main Content ===== */}
      <Card size="small" style={{ marginTop: 12, padding: 16 }}>
        {/* ⭐ 状态按钮永远显示：恢复原始图标，不使用普通按钮/弹窗 */}
        <div style={{ marginBottom: 16, display: "flex", gap: 18 }}>
          <Tooltip title="Pending">
            <PauseCircleOutlined
              style={{ fontSize: 28, color: "#b9900a", cursor: "pointer" }}
              onClick={() => updateStatus("Pending")}
            />
          </Tooltip>

          <Tooltip title="Ongoing">
            <SyncOutlined
              spin={currentTask.status === "Ongoing"}
              style={{ fontSize: 28, color: "#1677ff", cursor: "pointer" }}
              onClick={() => updateStatus("Ongoing")}
            />
          </Tooltip>

          <Tooltip title="Done">
            <CheckCircleOutlined
              style={{ fontSize: 28, color: "#52c41a", cursor: "pointer" }}
              onClick={() => updateStatus("Done")}
            />
          </Tooltip>

          <Tooltip title="Decline">
            <MinusCircleOutlined
              style={{ fontSize: 28, color: "#707070", cursor: "pointer" }}
              onClick={() => updateStatus("Decline")}
            />
          </Tooltip>
        </div>

        {/* ⭐ 只有有模板时才显示 WorkFlow 图 */}
        {!taskNotFound && (
          <WorkFlow
            taskId={taskId}
            projectName={projectName}
            user={user}
            inputs={taskInputs}
            outputs={taskOutputs}
            operation={taskOperation}
            operationLabel={taskOperation?.operation_name || "Manual Operation"}
            onOperationClick={executeOperation}
          />
        )}
      </Card>

      {/* 评论区域永远显示 */}
      <Divider />

      <Card size="small" style={{ marginTop: 12, background: "#fafafa" }}>
        <Input.TextArea
          rows={4}
          placeholder="Add your comment..."
          value={currentTask.comment || ""}
          onChange={(e) =>
            setCurrentTask({
              ...currentTask,
              comment: e.target.value,
            })
          }
        />

        <Button
          type="primary"
          style={{ marginTop: 12 }}
          onClick={async () => {
            const effectiveProjectId = getEffectiveProjectId();

            if (!effectiveProjectId) {
              messageApi.error("缺少项目ID，无法保存评论");
              return;
            }

            const updated = JSON.parse(JSON.stringify(projectWorkFlow));
            const task = findTaskNodeById(updated.taskTree, taskId);
            task.comment = currentTask.comment;

            const res = await updateWorkFlow({
              username: user.username,
              department: user.department,
              workflow: updated,
              projectId: effectiveProjectId,
            });

            res?.success
              ? messageApi.success("Comment saved!")
              : messageApi.error("Save failed");
          }}
        >
          Save Comment
        </Button>
      </Card>

      {/* Edit Task Modal */}
      <Modal
        title="Edit Task Name"
        open={editModalOpen}
        onOk={updateTaskName}
        onCancel={() => {
          if (!savingTaskName) {
            setEditModalOpen(false);
          }
        }}
        okText="Save"
        confirmLoading={savingTaskName}
        maskClosable={!savingTaskName}
      >
        <Form layout="vertical">
          <Form.Item label="Task Name">
            <Input
              value={newTaskName}
              placeholder="Enter new task name"
              onChange={(e) => setNewTaskName(e.target.value)}
              onBlur={(e) =>
                setNewTaskName(e.target.value.replace(ILLEGAL_REGEX, ""))
              }
              onPressEnter={updateTaskName}
              disabled={savingTaskName}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* Operation Loading Modal */}
      <Modal
        open={operationRunning}
        title="操作执行中"
        footer={null}
        closable={false}
        maskClosable={false}
        keyboard={false}
        centered
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <Spin />
          <span>{operationText || "正在执行，请稍候..."}</span>
        </div>
        <div style={{ marginTop: 12, color: "#666" }}>
          请不要关闭页面，也不要重复点击按钮。
        </div>
      </Modal>

      {/* Missing Email Modal: 必须点击确认才关闭 */}
      <Modal
        open={missingEmailModalOpen}
        title="缺少 Email 文件"
        closable={false}
        maskClosable={false}
        keyboard={false}
        centered
        footer={[
          <Button
            key="confirmMissingEmail"
            type="primary"
            onClick={() => setMissingEmailModalOpen(false)}
          >
            确定
          </Button>,
        ]}
      >
        <div style={{ fontSize: 16, lineHeight: 1.8 }}>{MISSING_EMAIL_TIP}</div>
        <div style={{ marginTop: 8, color: "#666" }}>
          请将 Email 文件放入当前 CalibrationID 的 Customer_Approval_Email 文件夹后，再重新点击 Fill_TCD08。
        </div>
      </Modal>
    </div>
  );
}
