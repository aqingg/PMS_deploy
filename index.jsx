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
  const { projectId, taskId } = useParams();
  const {
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

  // Modal
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [newTaskName, setNewTaskName] = useState("");

  // 操作执行中等待弹窗
  const [loadingModalOpen, setLoadingModalOpen] = useState(false);
  const [loadingText, setLoadingText] = useState("");

  // 允许中文，不允许真正危险字符。CalibrationID 文件夹重命名也依赖这个规则。
  const ILLEGAL_REGEX = /[/\\<>{}[\]"'`|]/g;

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

  const getNodeName = useCallback(
    (node) => String(node?.taskName || node?.name || node?.title || node?.label || "").trim(),
    []
  );

  const normalizeNodeName = useCallback(
    (value) =>
      String(value || "")
        .trim()
        .toLowerCase()
        .replace(/\s+/g, ""),
    []
  );

  const findTaskPathById = useCallback(
    (nodes, id, path = []) => {
      for (const node of nodes || []) {
        const nextPath = [...path, node];
        if (node.id === id) return nextPath;
        if (node.children?.length) {
          const res = findTaskPathById(node.children, id, nextPath);
          if (res) return res;
        }
      }
      return null;
    },
    []
  );

  const isCalibrationContainerName = useCallback(
    (name) => {
      const normalized = normalizeNodeName(name);
      const compact = normalized.replace(/[^a-z0-9]/g, "");
      return (
        normalized === "c.calibration" ||
        normalized === "calibration" ||
        normalized.endsWith(".calibration") ||
        normalized.includes("c.calibration") ||
        compact === "ccalibration" ||
        compact === "calibration"
      );
    },
    [normalizeNodeName]
  );

  const getCalibrationRenameContext = useCallback(() => {
    if (!projectWorkFlow?.taskTree) {
      return { shouldRename: false, reason: "workflow not loaded" };
    }

    const path = findTaskPathById(projectWorkFlow.taskTree, taskId);
    if (!path || path.length < 2) {
      return { shouldRename: false, reason: "task path not found" };
    }

    const parent = path[path.length - 2];
    const parentName = getNodeName(parent);

    // 标准判断：当前节点是 C.Calibration 的直接子节点。
    if (isCalibrationContainerName(parentName)) {
      return { shouldRename: true, parentName, path };
    }

    // 兼容判断：路径里最后一个 C.Calibration 节点正好是当前节点的父节点。
    const calibrationIndex = path.findIndex((node) =>
      isCalibrationContainerName(getNodeName(node))
    );
    if (calibrationIndex >= 0 && calibrationIndex === path.length - 2) {
      return { shouldRename: true, parentName: getNodeName(path[calibrationIndex]), path };
    }

    return {
      shouldRename: false,
      reason: `parent is ${parentName || "unknown"}, not C.Calibration`,
      parentName,
      path,
    };
  }, [projectWorkFlow, taskId, findTaskPathById, getNodeName, isCalibrationContainerName]);

  const deriveApplicationDirFromCalibrationRoot = (calibrationRoot) => {
    const value = String(calibrationRoot || "").trim();
    if (!value) return "";

    const normalized = value.replace(/\//g, "\\");
    const parts = normalized.split("\\").filter(Boolean);
    const appIndex = parts.findIndex((part) => part.toLowerCase() === "40.application");

    if (appIndex < 0) return "";

    const prefix = normalized.startsWith("\\\\") ? "\\\\" : "";
    return prefix + parts.slice(0, appIndex + 1).join("\\");
  };

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

  // ================================
  // 更新状态
  // ================================
  const updateStatus = async (newStatus) => {
    const updated = JSON.parse(JSON.stringify(projectWorkFlow));
    const task = findTaskNodeById(updated.taskTree, taskId);
    if (!task) return;

    task.status = newStatus;
    await updateWorkFlow({
      username: user.username,
      department: user.department,
      workflow: updated,
      projectId: Number(projectId),
    });
  };

  // ================================
  // 保存任务名
  // 如果当前节点是 C.Calibration 的直接子节点，则同步重命名本地 C 盘文件夹。
  // 只执行 folder rename，不复制、不删除、不修改子目录内容。
  // ================================
  const updateTaskName = async () => {
    const cleaned = newTaskName.replace(ILLEGAL_REGEX, "").trim();

    if (!cleaned) {
      messageApi.error("Task name cannot be empty");
      return;
    }

    if (!currentTask) return;

    const oldTaskName = String(currentTask.taskName || "").trim();
    if (!oldTaskName) return;

    const renameContext = getCalibrationRenameContext();
    const shouldRenameLocalFolder = oldTaskName !== cleaned && renameContext.shouldRename;

    console.log("[Calibration Rename] context:", {
      oldTaskName,
      newTaskName: cleaned,
      shouldRenameLocalFolder,
      reason: renameContext.reason,
      parentName: renameContext.parentName,
      path: renameContext.path?.map((node) => getNodeName(node)),
    });

    let applicationDir = "";
    let localFolderRenamed = false;

    try {
      if (shouldRenameLocalFolder) {
        setLoadingText("正在重命名本地 CalibrationID 文件夹，请稍候...");
        setLoadingModalOpen(true);

        const workspaceResult = await createCalibrationWorkspace(oldTaskName);
        if (!workspaceResult?.success) {
          messageApi.error(
            `8086 path calculation failed: ${
              workspaceResult?.message || "unknown error"
            }`
          );
          return;
        }

        const calibrationRoot = workspaceResult.paths?.calibration_root;
        applicationDir = deriveApplicationDirFromCalibrationRoot(calibrationRoot);

        if (!applicationDir) {
          messageApi.error(
            `Cannot derive 40.Application from calibration_root: ${calibrationRoot || "empty"}`
          );
          return;
        }

        const renameResult = await renameCalibrationFolder(
          applicationDir,
          oldTaskName,
          cleaned
        );

        if (!renameResult?.success) {
          messageApi.error(
            `Local folder rename failed: ${renameResult?.message || "unknown error"}`
          );
          return;
        }

        localFolderRenamed = Boolean(renameResult.renamed);
      }

      const updated = JSON.parse(JSON.stringify(projectWorkFlow));
      const node = findTaskNodeById(updated.taskTree, taskId);
      if (!node) return;

      node.taskName = cleaned;

      const res = await updateWorkFlow({
        username: user.username,
        department: user.department,
        workflow: updated,
        projectId: Number(projectId),
      });

      if (res.success) {
        setEditModalOpen(false);
        if (shouldRenameLocalFolder) {
          messageApi.success("Task name and local folder renamed.");
        } else {
          messageApi.success("Task name updated.");
        }
        return;
      }

      // 如果 workflow 保存失败，但本地目录已改名，尝试回滚，避免两边不一致。
      if (localFolderRenamed && applicationDir) {
        await renameCalibrationFolder(applicationDir, cleaned, oldTaskName);
      }
      messageApi.error("Update failed");
    } catch (error) {
      console.error("Update task name failed:", error);

      if (localFolderRenamed && applicationDir) {
        try {
          await renameCalibrationFolder(applicationDir, cleaned, oldTaskName);
        } catch (rollbackError) {
          console.error("Rollback local folder rename failed:", rollbackError);
        }
      }

      messageApi.error(error.message || "Update failed");
    } finally {
      setLoadingModalOpen(false);
    }
  };

  // ================================
  // 定义 Operation 行为
  // ================================
  async function handleHttpWithParameter(operation_detail) {
    // 0. 获取需要注入的参数名列表
    const { need_parameter: parameterNames } = operation_detail;

    if (!Array.isArray(parameterNames)) {
      throw new Error("配置错误：'need_parameter' 必须是一个数组。");
    }

    const parameterPromises = parameterNames.map((name) => getParameter(name));
    const parameterResults = await Promise.all(parameterPromises);

    const type = "local";
    const isTCD08Fill = operation_detail.url?.includes("/fillTCD08Report");
    let input_files = [];

    if (!isTCD08Fill) {
      const input_path = await getRealPathFromBackend({
        label: taskInputs[0]?.label,
        taskId,
        projectId,
        user,
        type,
      });
      input_files = await getOfficeFiles(input_path);
    }

    const output_path = await getRealPathFromBackend({
      label: taskOutputs[0]?.label,
      taskId,
      projectId,
      user,
      type,
    });

    // 1. 构建最终请求体
    const { url, method, body } = operation_detail;
    const finalBody = JSON.parse(JSON.stringify(body || {}));

    parameterNames.forEach((name, index) => {
      const parameterValue = parameterResults[index].parameter;
      finalBody[name] = parameterValue;
    });

    finalBody.template_paths = input_files;
    finalBody.save_path = output_path;

    if (isTCD08Fill) {
      finalBody.project_info = projectInfo;
      finalBody.projectId = Number(projectId);
      finalBody.taskId = taskId;
    }

    // 2. 发送请求
    const response = await fetch(url, {
      method,
      headers: {
        "Content-Type": "application/json",
      },
      body: finalBody ? JSON.stringify(finalBody) : undefined,
    });

    // 3. 错误处理
    if (!response.ok) {
      let errorMessage = `请求失败: ${response.status} ${response.statusText}`;
      try {
        const errorData = await response.json();
        if (errorData && errorData.message) {
          errorMessage = errorData.message;
        }
      } catch (e) {
        // 响应体不是 JSON 或为空
      }
      throw new Error(errorMessage);
    }

    // 4. 成功处理
    try {
      return await response.json();
    } catch (e) {
      return null;
    }
  }

  const handleOperationClick = async () => {
    if (!taskOperation) {
      message.warning("This task requires manual operation.");
      return;
    }

    const { operation_name, operation_detail } = taskOperation;
    const { type } = operation_detail;

    setLoadingText(`正在执行: ${operation_name}，请稍候...`);
    setLoadingModalOpen(true);

    try {
      switch (type) {
        case "httpWithParameter":
          await handleHttpWithParameter(operation_detail);
          break;
        case "httpWithoutParameter":
          break;
        default:
          break;
      }
    } catch (error) {
      console.error("操作失败:", error);
      messageApi.error(error.message || "操作失败，请查看控制台获取详情。");
    } finally {
      setLoadingModalOpen(false);
    }
  };

  // ======================================================
  // 提前拦截 — 如果 currentTask 未加载，直接 Loading
  // ======================================================
  if (!currentTask) {
    return (
      <>
        {contextHolder}
        <Spin tip="Loading Task..." />
      </>
    );
  }

  // ================================
  // UI
  // ================================
  return (
    <>
      {contextHolder}

      {/* Header */}
      <Card style={{ marginBottom: 16 }}>
        <Row justify="space-between" align="middle">
          <Col>
            <h1 style={{ marginBottom: 8 }}>{currentTask.taskName}</h1>
            <div style={{ color: "#666" }}>{taskDescription}</div>
          </Col>
          <Col>
            <Tooltip title="Edit Task Name">
              <Button
                shape="circle"
                icon={<EditOutlined />}
                onClick={() => {
                  setNewTaskName(currentTask.taskName);
                  setEditModalOpen(true);
                }}
              />
            </Tooltip>
          </Col>
        </Row>
      </Card>

      {/* ===== Main Content ===== */}
      <Card style={{ marginBottom: 16 }}>
        <Divider orientation="left">Status</Divider>
        <Row gutter={[12, 12]}>
          <Col>
            <Button
              icon={<PauseCircleOutlined />}
              onClick={() => updateStatus("Pending")}
            >
              Pending
            </Button>
          </Col>
          <Col>
            <Button
              icon={<SyncOutlined />}
              onClick={() => updateStatus("Ongoing")}
            >
              Ongoing
            </Button>
          </Col>
          <Col>
            <Button
              icon={<CheckCircleOutlined />}
              onClick={() => updateStatus("Done")}
            >
              Done
            </Button>
          </Col>
          <Col>
            <Button
              icon={<MinusCircleOutlined />}
              onClick={() => updateStatus("Decline")}
            >
              Decline
            </Button>
          </Col>
        </Row>
      </Card>

      {/* ⭐ 只有有模板时才显示 WorkFlow 图 */}
      {!taskNotFound && (
        <Card style={{ marginBottom: 16 }}>
          <WorkFlow
            inputs={taskInputs}
            outputs={taskOutputs}
            operation={taskOperation}
            operationLabel={taskOperation?.operation_name || "Manual Operation"}
            onOperationClick={handleOperationClick}
            taskId={taskId}
            projectName={projectName}
            user={user}
          />
        </Card>
      )}

      {/* 评论区域永远显示 */}
      <Card title="Comment">
        <Input.TextArea
          rows={4}
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
            const updated = JSON.parse(JSON.stringify(projectWorkFlow));
            const task = findTaskNodeById(updated.taskTree, taskId);
            if (!task) return;

            task.comment = currentTask.comment;
            const res = await updateWorkFlow({
              username: user.username,
              department: user.department,
              workflow: updated,
              projectId: Number(projectId),
            });
            res.success ? messageApi.success("Comment saved!") : messageApi.error("Save failed");
          }}
        >
          Save Comment
        </Button>
      </Card>

      {/* Edit Task Modal */}
      <Modal
        title="Edit Task Name"
        open={editModalOpen}
        onCancel={() => setEditModalOpen(false)}
        onOk={updateTaskName}
        okText="Save"
        destroyOnClose
      >
        <Form layout="vertical">
          <Form.Item label="Task Name">
            <Input
              value={newTaskName}
              onChange={(e) => setNewTaskName(e.target.value)}
              onBlur={(e) => setNewTaskName(e.target.value.replace(ILLEGAL_REGEX, ""))}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* 操作执行中等待弹窗 */}
      <Modal open={loadingModalOpen} footer={null} closable={false} centered>
        <div style={{ textAlign: "center", padding: "24px 0" }}>
          <Spin />
          <div style={{ marginTop: 16 }}>{loadingText}</div>
        </div>
      </Modal>
    </>
  );
}
